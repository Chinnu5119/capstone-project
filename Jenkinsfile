// CI/CD pipeline: GitHub -> Jenkins -> Amazon ECR -> Amazon EKS
// The Jenkins server (an EC2 instance) uses an IAM instance profile, so no AWS keys are stored in Jenkins.
// Required on the Jenkins node: docker, aws-cli v2, kubectl, envsubst (package: gettext-base).
pipeline {
  agent any

  options { timestamps(); disableConcurrentBuilds(); timeout(time: 30, unit: 'MINUTES') }

  environment {
    AWS_REGION   = 'ap-south-1'                 // <-- change to your region
    ACCOUNT_ID   = '123456789012'               // <-- change to your AWS account id
    CLUSTER_NAME = 'devops-dashboard-eks'       // <-- change to your EKS cluster name
    K8S_NS       = 'devops-dashboard'
    ECR_REGISTRY = "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
    BACKEND_REPO = "${ECR_REGISTRY}/devops-dashboard/backend"
    FRONTEND_REPO = "${ECR_REGISTRY}/devops-dashboard/frontend"
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
        script { env.IMAGE_TAG = sh(returnStdout: true, script: 'git rev-parse --short HEAD').trim() }
      }
    }

    stage('Test') {
      parallel {
        stage('Backend tests (pytest)') {
          steps {
            sh '''
              docker run --rm -v "$PWD/backend":/app -w /app python:3.12-slim \
                sh -c "pip install -q -r requirements-dev.txt && pytest -q"
            '''
          }
        }
        stage('Frontend build check') {
          steps {
            sh '''
              docker run --rm -v "$PWD/frontend":/ui -w /ui node:22-alpine \
                sh -c "npm ci && npm run build"
            '''
          }
        }
      }
    }

    stage('Build images') {
      steps {
        sh '''
          docker build -t $BACKEND_REPO:$IMAGE_TAG  -t $BACKEND_REPO:latest  ./backend
          docker build -t $FRONTEND_REPO:$IMAGE_TAG -t $FRONTEND_REPO:latest ./frontend
        '''
      }
    }

    stage('Push to ECR') {
      when { branch 'main' }
      steps {
        sh '''
          aws ecr get-login-password --region $AWS_REGION | \
            docker login --username AWS --password-stdin $ECR_REGISTRY
          docker push $BACKEND_REPO:$IMAGE_TAG
          docker push $BACKEND_REPO:latest
          docker push $FRONTEND_REPO:$IMAGE_TAG
          docker push $FRONTEND_REPO:latest
        '''
      }
    }

    stage('Deploy to EKS') {
      when { branch 'main' }
      steps {
        sh '''
          aws eks update-kubeconfig --region $AWS_REGION --name $CLUSTER_NAME

          kubectl apply -f k8s/namespace.yaml

          # Prometheus / Alertmanager config is read from the files in deploy/ (single source of truth)
          kubectl -n $K8S_NS create configmap prometheus-config \
            --from-file=prometheus.yml=deploy/prometheus/prometheus.yml \
            --from-file=alert_rules.yml=deploy/prometheus/alert_rules.yml \
            --dry-run=client -o yaml | kubectl apply -f -
          kubectl -n $K8S_NS create configmap alertmanager-config \
            --from-file=alertmanager.yml=deploy/alertmanager/alertmanager.yml \
            --dry-run=client -o yaml | kubectl apply -f -

          kubectl apply -f k8s/postgres.yaml -f k8s/prometheus.yaml -f k8s/alertmanager.yaml -f k8s/ingress.yaml
          # Only image placeholders are substituted; nothing else in the manifests is touched
          for f in backend frontend; do
            envsubst '${ECR_REGISTRY} ${IMAGE_TAG}' < k8s/$f.yaml | kubectl apply -f -
          done

          kubectl -n $K8S_NS rollout status deployment/backend  --timeout=180s
          kubectl -n $K8S_NS rollout status deployment/frontend --timeout=120s
        '''
      }
    }

    stage('Smoke test') {
      when { branch 'main' }
      steps {
        sh '''
          kubectl -n $K8S_NS run smoke-$BUILD_NUMBER --rm -i --restart=Never --image=curlimages/curl -- \
            curl -fsS http://backend:8000/api/health
        '''
      }
    }
  }

  post {
    always  { sh 'docker image prune -f || true' }
    failure { echo 'Build failed: check the stage logs above. The previous release keeps running.' }
  }
}
