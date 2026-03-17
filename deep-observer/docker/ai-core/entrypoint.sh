#!/bin/sh
set -eu

if [ -f "/root/.kube/config" ]; then
  cp /root/.kube/config /tmp/kubeconfig
  # Convert Windows-style .kube paths so kubectl can read kubeconfig inside Linux container.
  sed -i 's#C:\\Users\\[^\\]*\\.kube#/root/.kube#g' /tmp/kubeconfig || true
  sed -i 's#\\#/#g' /tmp/kubeconfig || true
  # Route local kube API endpoint through Docker host from inside container.
  sed -i 's#127.0.0.1#host.docker.internal#g' /tmp/kubeconfig || true
  # Kubernetes cert SANs can be host-specific; use local read-only access without CA verification.
  sed -i 's#^[[:space:]]*certificate-authority:.*#    insecure-skip-tls-verify: true#g' /tmp/kubeconfig || true
  export KUBECONFIG=/tmp/kubeconfig
fi

exec /app/ai-core
