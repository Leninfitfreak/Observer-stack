package main

import (
	"context"
	"log"

	"ai_observer_core/internal/api"
	"ai_observer_core/internal/brain"
	"ai_observer_core/internal/clickhouse"
	"ai_observer_core/internal/config"
	"ai_observer_core/internal/repository"
)

func main() {
	cfg, err := config.Load()
	if err != nil { log.Fatalf("config_load_failed err=%v", err) }
	ctx := context.Background()
	reader, err := clickhouse.New(cfg)
	if err != nil { log.Fatalf("clickhouse_init_failed err=%v", err) }
	repo, err := repository.New(cfg)
	if err != nil { log.Fatalf("postgres_init_failed err=%v", err) }
	defer repo.Close()
	if err := repo.Migrate(ctx); err != nil { log.Fatalf("postgres_migrate_failed err=%v", err) }
	server := api.New(cfg, reader, repo, brain.New(cfg.BrainURL))
	server.StartScheduler(ctx)
	log.Printf("ai_core_started port=%s project=%s cluster=%s", cfg.Port, cfg.ProjectID, cfg.ClusterID)
	if err := server.Engine().Run(":" + cfg.Port); err != nil { log.Fatalf("server_failed err=%v", err) }
}
