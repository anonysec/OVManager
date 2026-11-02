// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"math"
	"net/http"
	"strconv"
	"strings"

	"github.com/anonysec/OVManager/go/internal/config"
)

func bankerRound(f float64) int {
	floor := math.Floor(f)
	diff := f - floor
	if diff > 0.5 {
		return int(floor) + 1
	}
	if diff < 0.5 {
		return int(floor)
	}
	// exactly .5 → round to even
	if int64(floor)%2 == 0 {
		return int(floor)
	}
	return int(floor) + 1
}

// round1 is round(x, 1).
func round1(f float64) float64 {
	return math.Round(f*10) / 10
}

func clamp(v, low, high int) int {
	if v < low {
		return low
	}
	if v > high {
		return high
	}
	return v
}

func intQuery(r *http.Request, key string, def int) int {
	if v := r.URL.Query().Get(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func envFloat(key string, def float64, _ ...bool) float64 {
	if v := envOrFileTelemetry(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return def
}

func envOrFileTelemetry(key string) string {
	return config.EnvOrFile(key, "")
}

func newEventKey() string {
	for {
		buf := make([]byte, 16)
		if _, err := rand.Read(buf); err == nil {
			return hex.EncodeToString(buf)
		}
	}
}

func escapeLike(s string) string {
	s = strings.ReplaceAll(s, `\`, `\\`)
	s = strings.ReplaceAll(s, "%", `\%`)
	return strings.ReplaceAll(s, "_", `\_`)
}

func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

func nullStr(v sql.NullString) any {
	if !v.Valid || v.String == "" {
		return nil
	}
	return v.String
}

func derefInt(v *int64) int64 {
	if v == nil {
		return 0
	}
	return *v
}

func intOf(v sql.NullInt64) int {
	if !v.Valid {
		return 0
	}
	return int(v.Int64)
}

func f64(v any) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case int:
		return float64(n)
	case int64:
		return float64(n)
	}
	return 0
}

func toI64(v any) int64 {
	switch n := v.(type) {
	case float64:
		return int64(n)
	case int:
		return int64(n)
	case int64:
		return n
	}
	return 0
}

func boolOf(v any) bool {
	switch n := v.(type) {
	case bool:
		return n
	case int:
		return n != 0
	case int64:
		return n != 0
	case float64:
		return n != 0
	}
	return false
}

func boolInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
