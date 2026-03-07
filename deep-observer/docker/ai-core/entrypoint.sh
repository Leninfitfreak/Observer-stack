#!/bin/sh
set -eu

if [ -f "/root/.kube/config" ]; then
  cp /root/.kube/config /tmp/kubeconfig
  # Convert Windows-style Minikube paths so kubectl works inside Linux containers.
  sed -i 's#C:\\Users\\[^\\]*\\.minikube#/root/.minikube#g' /tmp/kubeconfig || true
  sed -i 's#\\#/#g' /tmp/kubeconfig || true
  # Route local Minikube API endpoint through Docker host from inside container.
  sed -i 's#127.0.0.1#host.docker.internal#g' /tmp/kubeconfig || true
  # Minikube cert SANs are host-specific; use local read-only access without CA verification.
  sed -i 's#^[[:space:]]*certificate-authority:.*#    insecure-skip-tls-verify: true#g' /tmp/kubeconfig || true
  export KUBECONFIG=/tmp/kubeconfig
fi

exec /app/ai-core
