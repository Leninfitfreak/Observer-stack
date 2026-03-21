package v2

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"
)

func RegisterRoutes(mux *http.ServeMux, service *Service) {
	mux.HandleFunc("/api/v2/dashboard", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 25*time.Second)
		defer cancel()
		start, end := parseRange(r.URL.Query().Get("start"), r.URL.Query().Get("end"), 24*time.Hour)
		response, err := service.BuildDashboard(ctx, ScopeRequest{
			Cluster:   normalizeScopeValue(r.URL.Query().Get("cluster")),
			Namespace: normalizeScopeValue(r.URL.Query().Get("namespace")),
			Service:   normalizeService(normalizeScopeValue(r.URL.Query().Get("service"))),
			Start:     start,
			End:       end,
		})
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, response)
	})

	mux.HandleFunc("/api/v2/incidents/", func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/api/v2/incidents/")
		parts := strings.Split(strings.Trim(path, "/"), "/")
		if len(parts) == 0 || strings.TrimSpace(parts[0]) == "" {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "incident not found"})
			return
		}
		incidentID := strings.TrimSpace(parts[0])
		ctx, cancel := context.WithTimeout(r.Context(), 25*time.Second)
		defer cancel()

		if len(parts) == 1 && r.Method == http.MethodGet {
			item, err := service.GetIncident(ctx, incidentID)
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
				return
			}
			if item == nil {
				writeJSON(w, http.StatusNotFound, map[string]string{"error": "incident not found"})
				return
			}
			writeJSON(w, http.StatusOK, item)
			return
		}

		if len(parts) == 2 && parts[1] == "view" && r.Method == http.MethodGet {
			start, end := parseRange(r.URL.Query().Get("start"), r.URL.Query().Get("end"), 24*time.Hour)
			view, err := service.BuildIncidentView(ctx, incidentID, ScopeRequest{
				Cluster:   normalizeScopeValue(r.URL.Query().Get("cluster")),
				Namespace: normalizeScopeValue(r.URL.Query().Get("namespace")),
				Service:   normalizeService(normalizeScopeValue(r.URL.Query().Get("service"))),
				Start:     start,
				End:       end,
			})
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
				return
			}
			writeJSON(w, http.StatusOK, view)
			return
		}

		if len(parts) == 3 && parts[1] == "reasoning" && parts[2] == "run" && r.Method == http.MethodPost {
			request, err := service.store.CreateReasoningRequest(ctx, incidentID, "manual")
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
				return
			}
			writeJSON(w, http.StatusAccepted, request)
			return
		}
		if len(parts) == 3 && parts[1] == "reasoning" && parts[2] == "retry" && r.Method == http.MethodPost {
			request, err := service.store.CreateReasoningRequest(ctx, incidentID, "retry")
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
				return
			}
			writeJSON(w, http.StatusAccepted, request)
			return
		}
		if len(parts) == 3 && parts[1] == "reasoning" && parts[2] == "history" && r.Method == http.MethodGet {
			runs, err := service.store.ListReasoningRuns(ctx, incidentID, 20)
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
				return
			}
			writeJSON(w, http.StatusOK, runs)
			return
		}
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "route not found"})
	})
}

func parseRange(startRaw, endRaw string, fallback time.Duration) (time.Time, time.Time) {
	now := time.Now().UTC()
	start := parseTime(startRaw)
	end := parseTime(endRaw)
	if start.IsZero() && end.IsZero() {
		end = now
		start = now.Add(-fallback)
	} else if start.IsZero() {
		start = end.Add(-fallback)
	} else if end.IsZero() {
		end = start.Add(fallback)
	}
	if end.Before(start) {
		end = start.Add(fallback)
	}
	return start.UTC(), end.UTC()
}

func parseTime(value string) time.Time {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Time{}
	}
	if parsed, err := time.Parse(time.RFC3339, value); err == nil {
		return parsed.UTC()
	}
	if millis, err := strconv.ParseInt(value, 10, 64); err == nil {
		return time.UnixMilli(millis).UTC()
	}
	return time.Time{}
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
