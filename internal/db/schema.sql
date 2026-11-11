-- OVManager schema baseline as shipped in 2.0.0.
--
-- This file is the only source of the schema. A new database applies it once
-- and is stamped with PRAGMA user_version = 1. Later releases add numbered
-- files under migrations/; nothing in this file changes after 2.0.0.

CREATE TABLE Admin (
  id INTEGER,
  username VARCHAR DEFAULT '' NOT NULL,
  password VARCHAR DEFAULT '' NOT NULL,
  is_owner BOOLEAN DEFAULT 0 NOT NULL,
  role VARCHAR DEFAULT 'admin' NOT NULL,
  telegram_id INTEGER,
  PRIMARY KEY (id),
  UNIQUE (username),
  UNIQUE (telegram_id)
);

CREATE TABLE User (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid VARCHAR,
  name VARCHAR DEFAULT '' NOT NULL,
  total BIGINT,
  used BIGINT,
  last_node_usage BIGINT DEFAULT 0 NOT NULL,
  node_usage VARCHAR DEFAULT '{}' NOT NULL,
  max_logins INTEGER DEFAULT 1 NOT NULL,
  expiry_date DATE DEFAULT CURRENT_TIMESTAMP NOT NULL,
  is_active BOOLEAN DEFAULT 1 NOT NULL,
  last_online DATETIME,
  tag VARCHAR,
  telegram_chat_id INTEGER,
  activation_token_hash VARCHAR(64),
  activation_token_expires_at REAL,
  UNIQUE (uuid),
  UNIQUE (name)
);

CREATE TABLE Node (
  id INTEGER,
  name VARCHAR DEFAULT '' NOT NULL,
  address VARCHAR DEFAULT '' NOT NULL,
  tunnel_address VARCHAR,
  protocol VARCHAR DEFAULT '' NOT NULL,
  ovpn_port INTEGER DEFAULT 0 NOT NULL,
  port INTEGER DEFAULT 0 NOT NULL,
  key VARCHAR DEFAULT '' NOT NULL,
  status BOOLEAN DEFAULT 1 NOT NULL,
  server_ca VARCHAR,
  country_code VARCHAR,
  latitude FLOAT,
  longitude FLOAT,
  extra_ports VARCHAR DEFAULT '' NOT NULL,
  node_contract_version INTEGER DEFAULT 0 NOT NULL,
  settings TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (id)
);

CREATE TABLE Setting (
  id INTEGER,
  tunnel_address VARCHAR,
  port INTEGER DEFAULT 1194 NOT NULL,
  protocol VARCHAR DEFAULT 'tcp' NOT NULL,
  timezone VARCHAR DEFAULT 'UTC' NOT NULL,
  bot_token VARCHAR,
  bot_enabled BOOLEAN DEFAULT 0 NOT NULL,
  default_days INTEGER DEFAULT 30 NOT NULL,
  default_traffic_gb INTEGER DEFAULT 100 NOT NULL,
  default_max_users INTEGER DEFAULT 1 NOT NULL,
  owner_telegram_id INTEGER,
  notify_expiry BOOLEAN DEFAULT 1 NOT NULL,
  notify_traffic BOOLEAN DEFAULT 1 NOT NULL,
  notify_node_down BOOLEAN DEFAULT 1 NOT NULL,
  alert_days_left INTEGER DEFAULT 3 NOT NULL,
  alert_usage_enabled BOOLEAN DEFAULT 1 NOT NULL,
  alert_usage_pct INTEGER DEFAULT 80 NOT NULL,
  alert_cpu_enabled BOOLEAN DEFAULT 1 NOT NULL,
  alert_cpu_pct INTEGER DEFAULT 85 NOT NULL,
  subscription_url_prefix VARCHAR,
  subscription_path VARCHAR DEFAULT 'sub' NOT NULL,
  sub_profile_title VARCHAR DEFAULT 'OVManager VPN' NOT NULL,
  sub_support_url VARCHAR DEFAULT '' NOT NULL,
  sub_announce VARCHAR DEFAULT '' NOT NULL,
  sub_update_interval_hours INTEGER DEFAULT 12 NOT NULL,
  urlpath VARCHAR DEFAULT '' NOT NULL,
  auto_backup_enabled BOOLEAN DEFAULT 0 NOT NULL,
  auto_backup_time VARCHAR DEFAULT '03:30' NOT NULL,
  auto_backup_keep INTEGER DEFAULT 50 NOT NULL,
  backup_encrypt_enabled BOOLEAN DEFAULT 0 NOT NULL,
  offsite_backup_target VARCHAR,
  telegram_backup_enabled BOOLEAN DEFAULT 0 NOT NULL,
  telegram_summary_time VARCHAR DEFAULT '09:00' NOT NULL,
  ssl_cert_file VARCHAR,
  ssl_key_file VARCHAR,
  acme_domain VARCHAR,
  acme_email VARCHAR,
  cert_method VARCHAR DEFAULT 'selfsigned' NOT NULL,
  panel_id VARCHAR DEFAULT '' NOT NULL,
  panel_url VARCHAR,
  panel_domain VARCHAR,
  bot_owner_setup_complete BOOLEAN DEFAULT 0 NOT NULL,
  backup_last_success_day VARCHAR,
  telegram_sent_day VARCHAR,
  snapshot_max_nodes INTEGER DEFAULT 0 NOT NULL,
  telegram_last_update_id BIGINT DEFAULT 0 NOT NULL,
  PRIMARY KEY (id)
);

CREATE TABLE Delivered (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subscription TEXT NOT NULL,
  event_key TEXT NOT NULL,
  ts REAL NOT NULL,
  UNIQUE (subscription, event_key)
);

CREATE TABLE NodeStat (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id INTEGER NOT NULL,
  created_at REAL NOT NULL,
  cpu REAL NOT NULL DEFAULT 0,
  memory REAL NOT NULL DEFAULT 0,
  live_count INTEGER NOT NULL DEFAULT 0,
  reachable INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE PendingUserRevocation (
  node_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  user_uuid TEXT NOT NULL,
  user_name TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_error TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (node_id, user_id)
);

CREATE TABLE TrafficStat (
  ts REAL PRIMARY KEY,
  total_used REAL NOT NULL DEFAULT 0,
  active_connections INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE UserNodeUsage (
  user_id INTEGER NOT NULL,
  node_id INTEGER NOT NULL,
  baseline INTEGER NOT NULL,
  epoch TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (user_id, node_id)
);

CREATE TABLE UserTrafficDaily (
  user_id INTEGER NOT NULL,
  day TEXT NOT NULL,
  bytes INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day)
);

CREATE INDEX idx_node_stat_node_ts ON NodeStat (node_id, created_at);
CREATE INDEX idx_nodes_name ON Node (name);
CREATE INDEX idx_nodes_status ON Node (status);
CREATE INDEX idx_traffic_stat_ts ON TrafficStat (ts);
CREATE INDEX idx_users_expiry ON User (expiry_date);
CREATE UNIQUE INDEX uq_admins_owner ON Admin (is_owner) WHERE is_owner = 1;
CREATE UNIQUE INDEX uq_users_activation_token_hash ON User (activation_token_hash)
  WHERE activation_token_hash IS NOT NULL AND activation_token_hash <> '';
