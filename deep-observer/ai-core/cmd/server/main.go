package main

import (
	"context"
	"log"
	"net/http"
	"os/signal"
	"syscall"
	"time"

	"deep-observer/ai-core/internal/api"
	"deep-observer/ai-core/internal/cluster"
	"deep-observer/ai-core/internal/config"
	"deep-observer/ai-core/internal/detector"
	"deep-observer/ai-core/internal/enterprise"
	"deep-observer/ai-core/internal/incidents"
)

func main() {
	cfg, err := config.Load(".env")
	if err != nil {
		log.Fatalf("load config: %v", err)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	store, err := incidents.NewStore(ctx, cfg.Postgres)
	if err != nil {
		log.Fatalf("connect postgres: %v", err)
	}
	defer store.Close()

	detectionEngine := detector.NewEngine(store, cfg.ClickHouse, cfg.Project, cfg.Alerts, cfg.Detector)
	go detectionEngine.Run(ctx)
	clusterEngine := cluster.NewIntelligenceEngine(store, cfg.Project.ClusterID, 5*time.Minute)
	go clusterEngine.Run(ctx)
	changeEngine := enterprise.NewChangeIntelligenceEngine(store, cfg.Project.ClusterID, 2*time.Minute)
	go changeEngine.Run(ctx)

	server := &http.Server{
		Addr:              ":" + cfg.APIPort,
		Handler:           api.NewRouter(store, cfg.ClickHouse, cfg.Project),
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		log.Printf("ai-core listening on %s", server.Addr)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("http server: %v", err)
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdownCtx)
}
