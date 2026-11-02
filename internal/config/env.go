// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package config

import (
	"os"
	"path/filepath"
	"strings"
)

// ParseEnv parses KEY=VALUE lines into a map, stripping quotes and trimming whitespace.
func ParseEnv(raw string) map[string]string {
	values := make(map[string]string)
	for _, line := range strings.Split(raw, "\n") {
		line = strings.TrimRight(strings.TrimSpace(line), "\r")
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		k, v, _ := strings.Cut(line, "=")
		values[strings.TrimSpace(k)] = strings.Trim(strings.TrimSpace(v), `"'`)
	}
	return values
}

// ReadEnvFile reads and parses a .env file from disk.
func ReadEnvFile(path string) map[string]string {
	raw, err := os.ReadFile(path)
	if err != nil {
		return make(map[string]string)
	}
	return ParseEnv(string(raw))
}

// EnvOrFile resolves an environment variable key: process environment wins,
// falling back to OVM_APP_DIR/.env or ./.env.
func EnvOrFile(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	var envPaths []string
	if appDir := os.Getenv("OVM_APP_DIR"); appDir != "" {
		envPaths = append(envPaths, filepath.Join(appDir, ".env"))
	}
	envPaths = append(envPaths, ".env")

	for _, p := range envPaths {
		if raw, err := os.ReadFile(p); err == nil {
			parsed := ParseEnv(string(raw))
			if v, ok := parsed[key]; ok && strings.TrimSpace(v) != "" {
				return strings.TrimSpace(v)
			}
		}
	}
	return def
}
