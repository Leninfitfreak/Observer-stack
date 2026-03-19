package cluster

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	"deep-observer/ai-core/internal/incidents"
)

type IntelligenceEngine struct {
	store     *incidents.Store
	clusterID string
	interval  time.Duration
}

func NewIntelligenceEngine(store *incidents.Store, clusterID string, interval time.Duration) *IntelligenceEngine {
	if interval <= 0 {
		interval = 5 * time.Minute
	}
	return &IntelligenceEngine{
		store:     store,
		clusterID: clusterID,
		interval:  interval,
	}
}

func (e *IntelligenceEngine) Run(ctx context.Context) {
	ticker := time.NewTicker(e.interval)
	defer ticker.Stop()
	e.refresh(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			e.refresh(ctx)
		}
	}
}

func (e *IntelligenceEngine) Refresh(ctx context.Context) error {
	return e.refresh(ctx)
}

func (e *IntelligenceEngine) refresh(ctx context.Context) error {
	clusterID := e.resolveClusterID(ctx)
	resources := []incidents.ClusterResource{}
	deployments, err := readKubernetesObjects(ctx, "deploy")
	if err == nil {
		for _, item := range deployments.Items {
			status := "healthy"
			if !containersHaveResourceLimits(item.Spec.Template.Spec.Containers) {
				status = "missing-limits"
			}
			resources = append(resources, incidents.ClusterResource{
				ClusterID:    clusterID,
				Namespace:    item.Metadata.Namespace,
				ResourceType: "deployment",
				ResourceName: item.Metadata.Name,
				Replicas:     readyReplicas(item.Status),
				Status:       status,
			})
			_ = e.store.UpsertServiceRegistryDetailed(
				ctx,
				"",
				clusterID,
				item.Metadata.Namespace,
				item.Metadata.Name,
				"deployment",
				item.Metadata.Name,
				"missing_telemetry",
				[]string{},
			)
		}
	}
	statefulSets, err := readKubernetesObjects(ctx, "statefulset")
	if err == nil {
		for _, item := range statefulSets.Items {
			status := "healthy"
			if !containersHaveResourceLimits(item.Spec.Template.Spec.Containers) {
				status = "missing-limits"
			}
			resources = append(resources, incidents.ClusterResource{
				ClusterID:    clusterID,
				Namespace:    item.Metadata.Namespace,
				ResourceType: "statefulset",
				ResourceName: item.Metadata.Name,
				Replicas:     readyReplicas(item.Status),
				Status:       status,
			})
			_ = e.store.UpsertServiceRegistryDetailed(
				ctx,
				"",
				clusterID,
				item.Metadata.Namespace,
				item.Metadata.Name,
				"statefulset",
				item.Metadata.Name,
				"missing_telemetry",
				[]string{},
			)
		}
	}
	daemonSets, err := readKubernetesObjects(ctx, "daemonset")
	if err == nil {
		for _, item := range daemonSets.Items {
			status := "healthy"
			if !containersHaveResourceLimits(item.Spec.Template.Spec.Containers) {
				status = "missing-limits"
			}
			resources = append(resources, incidents.ClusterResource{
				ClusterID:    clusterID,
				Namespace:    item.Metadata.Namespace,
				ResourceType: "daemonset",
				ResourceName: item.Metadata.Name,
				Replicas:     readyReplicas(item.Status),
				Status:       status,
			})
			_ = e.store.UpsertServiceRegistryDetailed(
				ctx,
				"",
				clusterID,
				item.Metadata.Namespace,
				item.Metadata.Name,
				"daemonset",
				item.Metadata.Name,
				"missing_telemetry",
				[]string{},
			)
		}
	}
	pods, err := readKubernetesPods(ctx)
	if err == nil {
		for _, pod := range pods.Items {
			resources = append(resources, incidents.ClusterResource{
				ClusterID:    clusterID,
				Namespace:    pod.Metadata.Namespace,
				ResourceType: "pod",
				ResourceName: pod.Metadata.Name,
				Replicas:     1,
				Status:       pod.Status.Phase,
				Node:         pod.Spec.NodeName,
			})
		}
	}
	services, err := readKubernetesServices(ctx)
	if err == nil {
		for _, svc := range services.Items {
			serviceType := strings.ToLower(strings.TrimSpace(svc.Spec.Type))
			if serviceType == "" {
				serviceType = "service"
			}
			_ = e.store.UpsertServiceRegistryDetailed(
				ctx,
				"",
				clusterID,
				svc.Metadata.Namespace,
				svc.Metadata.Name,
				serviceType,
				strings.TrimSpace(svc.Metadata.Annotations["deep-observer.io/deployment"]),
				"missing_telemetry",
				[]string{},
			)
			resources = append(resources, incidents.ClusterResource{
				ClusterID:    clusterID,
				Namespace:    svc.Metadata.Namespace,
				ResourceType: "service",
				ResourceName: svc.Metadata.Name,
				Replicas:     0,
				Status:       serviceType,
			})
		}
	}
	if len(resources) == 0 {
		registered, regErr := e.store.ListRegisteredServices(ctx, "", clusterID, "", 2000)
		if regErr != nil || len(registered) == 0 {
			return nil
		}
		for _, svc := range registered {
			if strings.TrimSpace(svc.ServiceName) == "" {
				continue
			}
			resources = append(resources, incidents.ClusterResource{
				ClusterID:    firstNonEmpty(strings.TrimSpace(svc.Cluster), clusterID),
				Namespace:    strings.TrimSpace(svc.Namespace),
				ResourceType: "service",
				ResourceName: svc.ServiceName,
				Replicas:     0,
				Status:       "telemetry_seen",
			})
		}
		if len(resources) == 0 {
			return nil
		}
	}
	return e.store.ReplaceClusterResources(ctx, clusterID, resources)
}

func (e *IntelligenceEngine) resolveClusterID(ctx context.Context) string {
	if trimmed := strings.TrimSpace(e.clusterID); trimmed != "" {
		return trimmed
	}
	cmd := kubectlCommand(ctx, "config", "current-context")
	output, err := cmd.Output()
	if err != nil {
		return ""
	}
	current := strings.TrimSpace(string(output))
	return current
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

func readKubernetesObjects(ctx context.Context, resource string) (*kubeObjectList, error) {
	cmd := kubectlCommand(ctx, "get", resource, "-A", "-o", "json")
	output, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("kubectl get %s: %w", resource, err)
	}
	var items kubeObjectList
	if err := json.Unmarshal(output, &items); err != nil {
		return nil, err
	}
	return &items, nil
}

func readKubernetesPods(ctx context.Context) (*kubePodList, error) {
	cmd := kubectlCommand(ctx, "get", "pods", "-A", "-o", "json")
	output, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("kubectl get pods: %w", err)
	}
	var items kubePodList
	if err := json.Unmarshal(output, &items); err != nil {
		return nil, err
	}
	return &items, nil
}

func readKubernetesServices(ctx context.Context) (*kubeServiceList, error) {
	cmd := kubectlCommand(ctx, "get", "services", "-A", "-o", "json")
	output, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("kubectl get services: %w", err)
	}
	var items kubeServiceList
	if err := json.Unmarshal(output, &items); err != nil {
		return nil, err
	}
	return &items, nil
}

func containersHaveResourceLimits(containers []kubeContainer) bool {
	if len(containers) == 0 {
		return false
	}
	for _, container := range containers {
		cpu := container.Resources.Limits["cpu"]
		mem := container.Resources.Limits["memory"]
		if cpu == "" || mem == "" {
			return false
		}
	}
	return true
}

type kubeObjectList struct {
	Items []kubeWorkload `json:"items"`
}

type kubeWorkload struct {
	Metadata kubeMetadata `json:"metadata"`
	Spec     struct {
		Template struct {
			Spec struct {
				Containers []kubeContainer `json:"containers"`
			} `json:"spec"`
		} `json:"template"`
	} `json:"spec"`
	Status kubeWorkloadStatus `json:"status"`
}

type kubeWorkloadStatus struct {
	ReadyReplicas int `json:"readyReplicas"`
	NumberReady   int `json:"numberReady"`
}

type kubeContainer struct {
	Resources struct {
		Limits map[string]string `json:"limits"`
	} `json:"resources"`
}

type kubePodList struct {
	Items []kubePod `json:"items"`
}

type kubeServiceList struct {
	Items []kubeService `json:"items"`
}

type kubePod struct {
	Metadata kubeMetadata `json:"metadata"`
	Spec     struct {
		NodeName string `json:"nodeName"`
	} `json:"spec"`
	Status struct {
		Phase string `json:"phase"`
	} `json:"status"`
}

type kubeService struct {
	Metadata kubeMetadata `json:"metadata"`
	Spec     struct {
		Type string `json:"type"`
	} `json:"spec"`
}

type kubeMetadata struct {
	Name        string            `json:"name"`
	Namespace   string            `json:"namespace"`
	Annotations map[string]string `json:"annotations"`
}

func readyReplicas(status kubeWorkloadStatus) int {
	if status.ReadyReplicas > 0 {
		return status.ReadyReplicas
	}
	return status.NumberReady
}

func kubectlCommand(ctx context.Context, args ...string) *exec.Cmd {
	if _, err := os.Stat("/tmp/kubeconfig"); err == nil {
		full := append([]string{"--kubeconfig", "/tmp/kubeconfig"}, args...)
		return exec.CommandContext(ctx, "kubectl", full...)
	}
	return exec.CommandContext(ctx, "kubectl", args...)
}
