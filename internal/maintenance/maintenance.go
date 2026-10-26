// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Package maintenance owns the backup, restore and urlpath transactions that
// both the panel (HTTP) and the CLI (ovm) share. It is the one implementation
// of each; callers go through here instead of internal/panel.
package maintenance

import (
	"github.com/anonysec/OVManager/go/internal/panel"
)

// BackupInfo is one restorable backup.
type BackupInfo = panel.BackupInfo

// OffsiteBackupTarget returns the configured offsite copy target.
func OffsiteBackupTarget(dataDir string) (string, error) {
	return panel.OffsiteBackupTarget(dataDir)
}

// CreateBackup takes one panel backup.
func CreateBackup(keep int, label, dataDir string) (string, error) {
	return panel.CreateBackup(keep, label, dataDir)
}

// ListStoredBackups are the restorable backups, newest first.
func ListStoredBackups(dataDir string) ([]BackupInfo, string) {
	return panel.ListStoredBackups(dataDir)
}

// RestoreStored restores a backup already in the backup dir.
func RestoreStored(name, actor, dataDir string) (bool, string, map[string]any) {
	return panel.RestoreStored(name, actor, dataDir)
}

// LiveURLPath is the prefix the panel is actually serving.
func LiveURLPath(dataDir string) (string, error) {
	return panel.LiveURLPath(dataDir)
}

// SetURLPath persists a new prefix.
func SetURLPath(value, dataDir string) (string, error) {
	return panel.SetURLPath(value, dataDir)
}

// ParseOffsiteTarget parses an offsite target string.
func ParseOffsiteTarget(target string) (user, host, path string, err error) {
	return panel.ParseOffsiteTarget(target)
}
