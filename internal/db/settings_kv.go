// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package db

import (
	"database/sql"
	"errors"
	"fmt"
)

// DBExecer is the exported execer interface; *sql.DB and *sql.Tx both satisfy it.
type DBExecer interface {
	Exec(query string, args ...any) (sql.Result, error)
	QueryRow(query string, args ...any) *sql.Row
}

// SettingsKey is a validated settings_kv key. Every `settings_kv` access
// goes through WriteSetting/ReadSetting with one of these constants — no raw
// string keys at call sites.
type SettingsKey string

const (
	KeyBackupLastSuccessDay SettingsKey = "backup.last_success_day"
	KeyTelegramSentDay      SettingsKey = "telegram_sent_day"
	KeySnapshotMaxNodes     SettingsKey = "telemetry.snapshot_max_nodes"
	KeyTelegramLastUpdateID SettingsKey = "telegram.last_update_id"
)

// Bundle: the three registered keys, for callers that pass them unqualified.
const (
	BackupLastSuccessDayKey = KeyBackupLastSuccessDay
	TelegramSentDayKey      = KeyTelegramSentDay
	SnapshotMaxNodesKey     = KeySnapshotMaxNodes
	TelegramLastUpdateIDKey = KeyTelegramLastUpdateID
)

// settingKeys is the registry of known keys. Adding a key here is the only
// way to persist a new setting-persisted value.
var settingKeys = map[SettingsKey]bool{
	KeyBackupLastSuccessDay: true,
	KeyTelegramSentDay:      true,
	KeySnapshotMaxNodes:     true,
	KeyTelegramLastUpdateID: true,
}

// ValidateSettingKey rejects keys outside the registry.
func ValidateSettingKey(k SettingsKey) error {
	if !settingKeys[k] {
		return fmt.Errorf("unknown settings_kv key: %q", k)
	}
	return nil
}

// WriteSetting writes one registered key+value atomically.
func WriteSetting(db DBExecer, k SettingsKey, value string, nowUnix int64) error {
	if err := ValidateSettingKey(k); err != nil {
		return err
	}
	_, err := db.Exec(
		`INSERT INTO settings_kv (key, value, updated_at) VALUES (?, ?, ?)
		 ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?`,
		string(k), value, nowUnix, value, nowUnix)
	return err
}

// ReadSetting reads a registered key; "" when absent.
func ReadSetting(db DBExecer, k SettingsKey) string {
	if err := ValidateSettingKey(k); err != nil {
		return ""
	}
	var v string
	_ = db.QueryRow(`SELECT value FROM settings_kv WHERE key = ?`, string(k)).Scan(&v)
	return v
}

var ErrUnknownSetting = errors.New("unknown settings_kv key")
