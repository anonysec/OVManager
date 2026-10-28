package panel

import (
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/anonysec/OVManager/go/internal/audit"
	"github.com/anonysec/OVManager/go/internal/notify"
	"github.com/anonysec/OVManager/go/internal/telemetry"
	"github.com/anonysec/OVManager/go/internal/version"
)

// Panel-settings validation (backend).
const (
	autoBackupKeepMin = 1
	autoBackupKeepMax = 500

	subTitleMax    = 64
	subAnnounceMax = 500
	subHoursMin    = 1
	subHoursMax    = 168
)

var (
	autoBackupTimeRe = regexp.MustCompile(`^([01]\d|2[0-3]):[0-5]\d$`)
	// setting.py's own domain rule: a dot is required.
	panelDomainRe = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$`)
	subSupportRe  = regexp.MustCompile(`(?i)^https?://`)
	urlPathRe     = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)
)

// thresholdBounds are the alert-threshold ranges (name, low, high).
var thresholdBounds = [][3]any{
	{"alert_days_left", 0, 365},
	{"alert_usage_pct", 1, 100},
	{"alert_cpu_pct", 1, 100},
}

// thresholdData is the alert-threshold block as served to the Settings UI.
func thresholdData(s settings) map[string]any {
	return map[string]any{
		"alert_days_left":     s.intOr("alert_days_left", 3),
		"alert_usage_enabled": s.boolean("alert_usage_enabled", true),
		"alert_usage_pct":     s.intOr("alert_usage_pct", 80),
		"alert_cpu_enabled":   s.boolean("alert_cpu_enabled", true),
		"alert_cpu_pct":       s.intOr("alert_cpu_pct", 85),
	}
}

func (h *Handler) getSettings(w http.ResponseWriter, r *http.Request) {
	s := h.settings()
	urlpath := h.urlpath()

	dbPrefix := s.strOr("subscription_url_prefix")
	subPrefixSource := dbPrefix
	if subPrefixSource == "" {
		subPrefixSource = envOrFile("SUBSCRIPTION_URL_PREFIX")
	}
	publicBase := strings.TrimRight(publicURLOr(r), "/")
	subscriptionPrefix := publicBase + "/"
	if urlpath != "" {
		subscriptionPrefix = publicBase + "/" + urlpath + "/"
	}
	if subPrefixSource != "" {
		subscriptionPrefix = strings.TrimRight(subPrefixSource, "/") + "/"
	}

	subPath := s.str("subscription_path", subscriptionPath())

	subInterval := s.num("sub_update_interval_hours", 12)
	if subInterval == 0 {
		subInterval = 12
	}
	data := map[string]any{
		"subscription_url_prefix":   subscriptionPrefix,
		"subscription_path":         strings.Trim(subPath, "/"),
		"timezone":                  s.str("timezone", "UTC"),
		"panel_version":             version.Version,
		"bot_token":                 maskedBotToken(s),
		"bot_configured":            s.strOr("bot_token") != "",
		"bot_enabled":               s.boolean("bot_enabled", false),
		"telegram_summary_time":     s.str("telegram_summary_time", "09:00"),
		"default_days":              orDefault(s.num("default_days", 30), 30),
		"default_traffic_gb":        orDefault(s.num("default_traffic_gb", 100), 100),
		"default_max_users":         s.numOrNull("default_max_users"),
		"offsite_backup_target":     s.strOr("offsite_backup_target"),
		"owner_telegram_id":         s.numOrNull("owner_telegram_id"),
		"urlpath":                   urlpath,
		"panel_domain":              s.nullStr("panel_domain"),
		"sub_profile_title":         s.strOr("sub_profile_title"),
		"sub_support_url":           s.strOr("sub_support_url"),
		"sub_announce":              s.strOr("sub_announce"),
		"sub_update_interval_hours": subInterval,
		"notify_expiry":             s.boolean("notify_expiry", true),
		"notify_traffic":            s.boolean("notify_traffic", true),
		"notify_node_down":          s.boolean("notify_node_down", true),
		"auto_backup_enabled":       s.boolean("auto_backup_enabled", false),
		"auto_backup_time":          s.str("auto_backup_time", "03:30"),
		"auto_backup_keep":          orDefault(s.num("auto_backup_keep", 50), 50),
		"telegram_backup_enabled":   s.boolean("telegram_backup_enabled", false),
		"telegram_backup_available": s.strOr("bot_token") != "",
		"panel_id":                  s.strOr("panel_id"),
	}
	for k, v := range thresholdData(s) {
		data[k] = v
	}
	envelope(w, true, "Settings retrieved successfully", data)
}

func orDefault(v, def int) int {
	if v == 0 {
		return def
	}
	return v
}

// maskedBotToken is the GET shape of the stored token: last four characters
// only — the secret itself never leaves the row.
func maskedBotToken(s settings) any {
	if s.strOr("bot_token") == "" {
		return nil
	}
	return notify.MaskToken(s.strOr("bot_token"))
}

// publicURLOr is (config.PUBLIC_URL or str(request.base_url)).
func publicURLOr(r *http.Request) string {
	if v := strings.TrimSpace(envOrFile("PUBLIC_URL")); v != "" {
		return v
	}
	return baseURL(r)
}

type timezoneUpdate struct {
	Timezone string `json:"timezone"`
}

func (h *Handler) updateTimezone(w http.ResponseWriter, r *http.Request) {
	var payload timezoneUpdate
	if !decodeBody(w, r, &payload) {
		return
	}
	tz := strings.TrimSpace(payload.Timezone)
	if tz == "" {
		tz = "UTC"
	}
	if tz != "UTC" {
		if _, err := time.LoadLocation(tz); err != nil {
			envelope(w, false, "Invalid timezone: "+tz, nil)
			return
		}
	}
	if err := setColumns(h.Svc.DB(), map[string]any{"timezone": tz}); err != nil {
		envelope(w, false, "Invalid timezone: "+tz, nil)
		return
	}
	envelope(w, true, "Timezone updated", map[string]any{"timezone": tz})
}

type subscriptionUpdate struct {
	SubscriptionURLPrefix  *string `json:"subscription_url_prefix"`
	SubscriptionPath       *string `json:"subscription_path"`
	SubProfileTitle        *string `json:"sub_profile_title"`
	SubSupportURL          *string `json:"sub_support_url"`
	SubAnnounce            *string `json:"sub_announce"`
	SubUpdateIntervalHours *int    `json:"sub_update_interval_hours"`
}

func (h *Handler) updateSubscription(w http.ResponseWriter, r *http.Request) {
	var payload subscriptionUpdate
	if !decodeBody(w, r, &payload) {
		return
	}
	// Validate the whole payload before anything is written.
	if payload.SubProfileTitle != nil && len(strings.TrimSpace(*payload.SubProfileTitle)) > subTitleMax {
		envelope(w, false, "Subscription title must be at most "+strconv.Itoa(subTitleMax)+" characters", nil)
		return
	}
	if payload.SubAnnounce != nil && len(strings.TrimSpace(*payload.SubAnnounce)) > subAnnounceMax {
		envelope(w, false, "Announcement must be at most "+strconv.Itoa(subAnnounceMax)+" characters", nil)
		return
	}
	if payload.SubSupportURL != nil {
		if support := strings.TrimSpace(*payload.SubSupportURL); support != "" && !subSupportRe.MatchString(support) {
			envelope(w, false, "Support link must start with http:// or https://", nil)
			return
		}
	}
	if payload.SubUpdateIntervalHours != nil &&
		(*payload.SubUpdateIntervalHours < subHoursMin || *payload.SubUpdateIntervalHours > subHoursMax) {
		envelope(w, false, "sub_update_interval_hours must be between 1 and 168", nil)
		return
	}

	updates := map[string]any{}
	if payload.SubscriptionURLPrefix != nil {
		updates["subscription_url_prefix"] = strings.TrimSpace(*payload.SubscriptionURLPrefix)
	}
	if payload.SubscriptionPath != nil {
		requested := strings.Trim(*payload.SubscriptionPath, "/")
		if requested == "" || requested != strings.Trim(subscriptionPath(), "/") {
			envelope(w, false, "Subscription path changes require a restart and route configuration update",
				map[string]any{"subscription_path": strings.Trim(subscriptionPath(), "/")})
			return
		}
		updates["subscription_path"] = requested
	}
	if payload.SubProfileTitle != nil {
		updates["sub_profile_title"] = strings.TrimSpace(*payload.SubProfileTitle)
	}
	if payload.SubSupportURL != nil {
		updates["sub_support_url"] = strings.TrimSpace(*payload.SubSupportURL)
	}
	if payload.SubAnnounce != nil {
		updates["sub_announce"] = strings.TrimSpace(*payload.SubAnnounce)
	}
	if payload.SubUpdateIntervalHours != nil {
		updates["sub_update_interval_hours"] = *payload.SubUpdateIntervalHours
	}
	if err := setColumns(h.Svc.DB(), updates); err != nil {
		envelope(w, false, "Subscription link settings updated", nil)
		return
	}
	s := h.settings()
	envelope(w, true, "Subscription link settings updated", map[string]any{
		"subscription_url_prefix":   s.strOr("subscription_url_prefix"),
		"subscription_path":         s.strOr("subscription_path"),
		"sub_profile_title":         s.strOr("sub_profile_title"),
		"sub_support_url":           s.strOr("sub_support_url"),
		"sub_announce":              s.strOr("sub_announce"),
		"sub_update_interval_hours": s.intOr("sub_update_interval_hours", 12),
	})
}

type domainUpdate struct {
	PanelDomain *string `json:"panel_domain"`
}

func (h *Handler) updateDomain(w http.ResponseWriter, r *http.Request) {
	var payload domainUpdate
	if !decodeBody(w, r, &payload) {
		return
	}
	domain := ""
	if payload.PanelDomain != nil {
		domain = strings.TrimRight(strings.ToLower(strings.TrimSpace(*payload.PanelDomain)), ".")
	}
	if domain != "" && !panelDomainRe.MatchString(domain) {
		envelope(w, false,
			"Enter a bare domain name (e.g. vpn.example.com) — no scheme, port or path.", nil)
		return
	}
	var value any
	msg := "VPN domain cleared — .ovpn files will use node IPs"
	if domain != "" {
		value = domain
		msg = "VPN domain updated"
	}
	if err := setColumns(h.Svc.DB(), map[string]any{"panel_domain": value}); err != nil {
		envelope(w, false, "VPN domain update failed", nil)
		return
	}
	envelope(w, true, msg, map[string]any{"panel_domain": domain})
}

type botConfigUpdate struct {
	BotToken              *string `json:"bot_token"`
	BotEnabled            *bool   `json:"bot_enabled"`
	DefaultDays           *int    `json:"default_days"`
	DefaultTrafficGB      *int    `json:"default_traffic_gb"`
	DefaultMaxUsers       *int    `json:"default_max_users"`
	OffsiteBackupTarget   *string `json:"offsite_backup_target"`
	OwnerTelegramID       *int    `json:"owner_telegram_id"`
	NotifyExpiry          *bool   `json:"notify_expiry"`
	NotifyTraffic         *bool   `json:"notify_traffic"`
	NotifyNodeDown        *bool   `json:"notify_node_down"`
	AlertDaysLeft         *int    `json:"alert_days_left"`
	AlertUsageEnabled     *bool   `json:"alert_usage_enabled"`
	AlertUsagePct         *int    `json:"alert_usage_pct"`
	AlertCPUEnabled       *bool   `json:"alert_cpu_enabled"`
	AlertCPUPct           *int    `json:"alert_cpu_pct"`
	AutoBackupEnabled     *bool   `json:"auto_backup_enabled"`
	AutoBackupTime        *string `json:"auto_backup_time"`
	AutoBackupKeep        *int    `json:"auto_backup_keep"`
	TelegramBackupEnabled *bool   `json:"telegram_backup_enabled"`
	TelegramSummaryTime   *string `json:"telegram_summary_time"`
}

// columns maps each request field to its DB column.
var botConfigColumns = []struct {
	key    string
	column string
	value  func(botConfigUpdate) (any, bool)
}{
	{"bot_token", "bot_token", func(p botConfigUpdate) (any, bool) {
		if p.BotToken == nil {
			return nil, false
		}
		if v := strings.TrimSpace(*p.BotToken); v != "" {
			return v, true
		}
		return nil, true // an empty token clears the column
	}},
	{"bot_enabled", "bot_enabled", func(p botConfigUpdate) (any, bool) { return boolOrNil(p.BotEnabled) }},
	{"default_days", "default_days", func(p botConfigUpdate) (any, bool) { return intOrNil(p.DefaultDays) }},
	{"default_traffic_gb", "default_traffic_gb", func(p botConfigUpdate) (any, bool) { return intOrNil(p.DefaultTrafficGB) }},
	{"default_max_users", "default_max_users", func(p botConfigUpdate) (any, bool) { return intOrNil(p.DefaultMaxUsers) }},
	{"offsite_backup_target", "offsite_backup_target", func(p botConfigUpdate) (any, bool) { return strOrNil(p.OffsiteBackupTarget) }},
	{"owner_telegram_id", "owner_telegram_id", func(p botConfigUpdate) (any, bool) { return intOrNil(p.OwnerTelegramID) }},
	{"notify_expiry", "notify_expiry", func(p botConfigUpdate) (any, bool) { return boolOrNil(p.NotifyExpiry) }},
	{"notify_traffic", "notify_traffic", func(p botConfigUpdate) (any, bool) { return boolOrNil(p.NotifyTraffic) }},
	{"notify_node_down", "notify_node_down", func(p botConfigUpdate) (any, bool) { return boolOrNil(p.NotifyNodeDown) }},
	{"alert_days_left", "alert_days_left", func(p botConfigUpdate) (any, bool) { return intOrNil(p.AlertDaysLeft) }},
	{"alert_usage_enabled", "alert_usage_enabled", func(p botConfigUpdate) (any, bool) { return boolOrNil(p.AlertUsageEnabled) }},
	{"alert_usage_pct", "alert_usage_pct", func(p botConfigUpdate) (any, bool) { return intOrNil(p.AlertUsagePct) }},
	{"alert_cpu_enabled", "alert_cpu_enabled", func(p botConfigUpdate) (any, bool) { return boolOrNil(p.AlertCPUEnabled) }},
	{"alert_cpu_pct", "alert_cpu_pct", func(p botConfigUpdate) (any, bool) { return intOrNil(p.AlertCPUPct) }},
	{"auto_backup_enabled", "auto_backup_enabled", func(p botConfigUpdate) (any, bool) { return boolOrNil(p.AutoBackupEnabled) }},
	{"auto_backup_time", "auto_backup_time", func(p botConfigUpdate) (any, bool) { return strOrNil(p.AutoBackupTime) }},
	{"auto_backup_keep", "auto_backup_keep", func(p botConfigUpdate) (any, bool) { return intOrNil(p.AutoBackupKeep) }},
	{"telegram_backup_enabled", "telegram_backup_enabled", func(p botConfigUpdate) (any, bool) { return boolOrNil(p.TelegramBackupEnabled) }},
	{"telegram_summary_time", "telegram_summary_time", func(p botConfigUpdate) (any, bool) {
		if p.TelegramSummaryTime == nil {
			return nil, false
		}
		v := strings.TrimSpace(*p.TelegramSummaryTime)
		if v == "" {
			return "09:00", true // blank resets to the default slot
		}
		return v, true
	}},
}

func boolOrNil(v *bool) (any, bool) {
	if v == nil {
		return nil, false
	}
	return *v, true
}

func intOrNil(v *int) (any, bool) {
	if v == nil {
		return nil, false
	}
	return *v, true
}

func strOrNil(v *string) (any, bool) {
	if v == nil {
		return nil, false
	}
	trimmed := strings.TrimSpace(*v)
	if trimmed == "" {
		return nil, true
	}
	return trimmed, true
}

func (h *Handler) updateBotConfig(w http.ResponseWriter, r *http.Request) {
	var payload botConfigUpdate
	if !decodeBody(w, r, &payload) {
		return
	}
	// Make sure a settings row exists before pointing columns at it
	// (readSettings seeds it — a 0-row UPDATE would otherwise silently pass,
	// see tls.go's issuance flow for the same trap).
	readSettings(h.Svc.DB())
	if payload.AutoBackupTime != nil && !autoBackupTimeRe.MatchString(*payload.AutoBackupTime) {
		envelope(w, false, "auto_backup_time must be a valid 24-hour time in HH:MM format", nil)
		return
	}
	if payload.TelegramSummaryTime != nil {
		if v := strings.TrimSpace(*payload.TelegramSummaryTime); v != "" && !autoBackupTimeRe.MatchString(v) {
			envelope(w, false, "telegram_summary_time must be a valid 24-hour time in HH:MM format", nil)
			return
		}
	}
	if payload.AutoBackupKeep != nil && (*payload.AutoBackupKeep < autoBackupKeepMin || *payload.AutoBackupKeep > autoBackupKeepMax) {
		envelope(w, false, "auto_backup_keep must be between 1 and 500", nil)
		return
	}
	// Offsite backup copies are not implemented: the SSH/rsync copy that this
	// setting used to advertise was never wired up. Re-adding the control
	// requires a real implementation; do not re-add the dead field here.
	if payload.OffsiteBackupTarget != nil && strings.TrimSpace(*payload.OffsiteBackupTarget) != "" {
		if _, _, _, err := ParseOffsiteTarget(*payload.OffsiteBackupTarget); err != nil {
			envelope(w, false, err.Error(), nil)
			return
		}
	}
	for _, bound := range thresholdBounds {
		name := bound[0].(string)
		low, high := bound[1].(int), bound[2].(int)
		var value *int
		switch name {
		case "alert_days_left":
			value = payload.AlertDaysLeft
		case "alert_usage_pct":
			value = payload.AlertUsagePct
		case "alert_cpu_pct":
			value = payload.AlertCPUPct
		}
		if value != nil && (*value < low || *value > high) {
			envelope(w, false, name+" must be between "+strconv.Itoa(low)+" and "+strconv.Itoa(high), nil)
			return
		}
	}
	if payload.TelegramBackupEnabled != nil && *payload.TelegramBackupEnabled {
		current := h.settings()
		token := current.strOr("bot_token")
		if payload.BotToken != nil && strings.TrimSpace(*payload.BotToken) != "" {
			token = strings.TrimSpace(*payload.BotToken)
		}
		ownerID := current.numOrNull("owner_telegram_id")
		if payload.OwnerTelegramID != nil {
			ownerID = *payload.OwnerTelegramID
		}
		if token == "" || ownerID == nil {
			envelope(w, false,
				"Configure the Telegram bot token and owner chat before enabling Telegram backups", nil)
			return
		}
	}

	updates := map[string]any{}
	for _, col := range botConfigColumns {
		if value, ok := col.value(payload); ok {
			updates[col.column] = value
		}
	}
	if err := setColumns(h.Svc.DB(), updates); err != nil {
		envelope(w, false, "Bot config update failed", nil)
		return
	}

	s := h.settings()
	data := map[string]any{
		"bot_configured":            s.strOr("bot_token") != "",
		"bot_enabled":               s.boolean("bot_enabled", false),
		"default_days":              s.numOrNull("default_days"),
		"default_traffic_gb":        s.numOrNull("default_traffic_gb"),
		"default_max_users":         s.numOrNull("default_max_users"),
		"owner_telegram_id":         s.numOrNull("owner_telegram_id"),
		"notify_expiry":             s.boolean("notify_expiry", true),
		"notify_traffic":            s.boolean("notify_traffic", true),
		"notify_node_down":          s.boolean("notify_node_down", true),
		"auto_backup_enabled":       s.boolean("auto_backup_enabled", false),
		"auto_backup_time":          s.str("auto_backup_time", "03:30"),
		"auto_backup_keep":          orDefault(s.num("auto_backup_keep", 50), 50),
		"telegram_backup_enabled":   s.boolean("telegram_backup_enabled", false),
		"telegram_backup_available": s.strOr("bot_token") != "",
		"telegram_summary_time":     s.str("telegram_summary_time", "09:00"),
	}
	for k, v := range thresholdData(s) {
		data[k] = v
	}
	// The auto-backup schedule lives in the scheduler (Phase 5+); the settings
	// write is what the API contract covers here.
	audit.Record(h.Svc.DB(), panelActor(h, r), "admin.settings", "info",
		"Panel settings updated.", map[string]any{"target": "bot_config"})
	envelope(w, true, "Bot config updated", data)
}

type alertTestUpdate struct {
	Channel string `json:"channel"`
}

func (h *Handler) testAlert(w http.ResponseWriter, r *http.Request) {
	channel := "telegram"
	var payload alertTestUpdate
	if r.ContentLength != 0 {
		if err := decodeRawBody(r, &payload); err == nil && strings.TrimSpace(payload.Channel) != "" {
			channel = strings.TrimSpace(payload.Channel)
		}
	}
	channel = strings.ToLower(channel)
	if channel != "telegram" {
		envelope(w, false, "Unsupported alert channel: "+channel, nil)
		return
	}
	sent := telemetry.SendTelegram(h.Svc.DB(), "OVManager test alert — Telegram notifications are wired up.")
	msg := "Telegram test failed — check the bot token, owner chat ID and that the bot is enabled"
	if sent {
		msg = "Test alert sent to Telegram"
	}
	envelope(w, sent, msg, map[string]any{"channel": "telegram", "sent": sent})
}

type urlPathUpdate struct {
	URLPath string `json:"urlpath"`
}

func (h *Handler) updateURLPath(w http.ResponseWriter, r *http.Request) {
	var payload urlPathUpdate
	if !decodeBody(w, r, &payload) {
		return
	}
	value := strings.Trim(payload.URLPath, "/")
	if !validURLPath(value) {
		envelope(w, false, "URL path must contain only letters, numbers, dashes, and underscores", nil)
		return
	}
	if value != "" && reservedPrefixes()[strings.ToLower(value)] {
		envelope(w, false, "'"+value+"' is reserved and cannot be used as the panel URL path", nil)
		return
	}
	newValue, err := h.setURLPath(value)
	if err != nil {
		envelope(w, false, err.Error(), nil)
		return
	}
	msg := "URL path cleared — panel now served at root."
	panelURL := "/"
	if newValue != "" {
		msg = "URL path updated — panel moved to the new path immediately."
		panelURL = "/" + newValue
	}
	audit.Record(h.Svc.DB(), panelActor(h, r), "admin.urlpath", "info",
		"Panel URL path changed.", map[string]any{"target": newValue})
	envelope(w, true, msg, map[string]any{"urlpath": newValue, "panel_url": panelURL})
}

// validURLPath is validation.validate_urlpath (single regex, 64 char cap).
func validURLPath(value string) bool {
	if value == "" {
		return true
	}
	return len(value) <= 64 && urlPathRe.MatchString(value)
}

// --- /server/info (observability/server_info.py) ---

var (
	cpuMu       sync.Mutex
	lastCPUIdle float64
	lastCPUTot  float64
)

func (h *Handler) serverInfo(w http.ResponseWriter, r *http.Request) {
	info := map[string]any{
		"cpu": cpuPercent(), "memory_total": 0, "memory_used": 0, "memory_percent": 0.0,
		"disk_total": 0, "disk_used": 0, "disk_percent": 0.0, "uptime": 0,
	}
	if total, available, ok := memInfo(); ok && total > 0 {
		used := total - available
		info["memory_total"] = total
		info["memory_used"] = used
		info["memory_percent"] = round1(float64(used) / float64(total) * 100)
	}
	var stat syscall.Statfs_t
	if err := syscall.Statfs("/", &stat); err == nil {
		total := stat.Blocks * uint64(stat.Bsize)
		used := (stat.Blocks - stat.Bavail) * uint64(stat.Bsize)
		info["disk_total"] = total
		info["disk_used"] = used
		if total > 0 {
			info["disk_percent"] = round1(float64(used) / float64(total) * 100)
		}
	}
	if raw, err := os.ReadFile("/proc/uptime"); err == nil {
		if fields := strings.Fields(string(raw)); len(fields) > 0 {
			if secs, err := strconv.ParseFloat(fields[0], 64); err == nil {
				info["uptime"] = int(secs)
			}
		}
	}
	envelope(w, true, "Server information retrieved successfully", info)
}

// cpuPercent mirrors psutil.cpu_percent(interval=None): the delta since the
// previous call, so the first call reports 0.
func cpuPercent() float64 {
	raw, err := os.ReadFile("/proc/stat")
	if err != nil {
		return 0.0
	}
	line, _, _ := strings.Cut(string(raw), "\n")
	fields := strings.Fields(line)
	if len(fields) < 5 {
		return 0.0
	}
	var total, idle float64
	for i, f := range fields[1:] {
		v, err := strconv.ParseFloat(f, 64)
		if err != nil {
			return 0.0
		}
		total += v
		if i == 3 { // idle
			idle = v
		}
	}
	cpuMu.Lock()
	defer cpuMu.Unlock()
	prevIdle, prevTotal := lastCPUIdle, lastCPUTot
	lastCPUIdle, lastCPUTot = idle, total
	if prevTotal == 0 || total <= prevTotal {
		return 0.0
	}
	return round1((1 - (idle-prevIdle)/(total-prevTotal)) * 100)
}

// memInfo reads MemTotal/MemAvailable in bytes.
func memInfo() (total, available uint64, ok bool) {
	raw, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return 0, 0, false
	}
	for _, line := range strings.Split(string(raw), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		value, err := strconv.ParseUint(fields[1], 10, 64)
		if err != nil {
			continue
		}
		switch fields[0] {
		case "MemTotal:":
			total = value * 1024
		case "MemAvailable:":
			available = value * 1024
		}
	}
	return total, available, total > 0
}

func round1(v float64) float64 {
	return float64(int(v*10+sign(v)*0.5)) / 10
}

func sign(v float64) float64 {
	if v < 0 {
		return -1
	}
	return 1
}

var _ = filepath.Join
