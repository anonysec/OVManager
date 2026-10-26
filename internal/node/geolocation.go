// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"encoding/json"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

type GeoResult struct {
	CountryCode string  `json:"countryCode"`
	Lat         float64 `json:"lat"`
	Lon         float64 `json:"lon"`
	Status      string  `json:"status"`
}

var (
	geoCacheMu sync.RWMutex
	geoCache   = map[string]geoCacheEntry{}
)

type geoCacheEntry struct {
	data      *GeoResult
	expiresAt time.Time
}

// geolocateBaseURL allows testing with local httptest server.
var geolocateBaseURL = "http://ip-api.com"

var geolocateHTTPClient = &http.Client{
	Timeout: 4 * time.Second,
}

// Geolocate looks up country code and coordinates for an address (hostname or IP).
// It returns countryCode, latitude, longitude, and an ok boolean.
func Geolocate(address string) (countryCode string, lat float64, lon float64, ok bool) {
	host := extractHost(address)
	if host == "" {
		return "", 0, 0, false
	}

	geoCacheMu.RLock()
	if entry, exists := geoCache[host]; exists && time.Now().Before(entry.expiresAt) {
		geoCacheMu.RUnlock()
		if entry.data == nil {
			return "", 0, 0, false
		}
		return entry.data.CountryCode, entry.data.Lat, entry.data.Lon, true
	}
	geoCacheMu.RUnlock()

	ip := resolveIP(host)
	if ip == "" {
		cacheGeo(host, nil)
		return "", 0, 0, false
	}

	// ip-api.com free tier: plain HTTP (HTTPS gives 403 SSL unavailable on free tier).
	resp, err := geolocateHTTPClient.Get(geolocateBaseURL + "/json/" + url.PathEscape(ip) + "?fields=status,countryCode,lat,lon")
	if err != nil {
		return "", 0, 0, false
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", 0, 0, false
	}

	var res GeoResult
	if err := json.NewDecoder(resp.Body).Decode(&res); err != nil {
		return "", 0, 0, false
	}

	if res.Status != "success" || len(res.CountryCode) < 2 || len(res.CountryCode) > 3 {
		cacheGeo(host, nil)
		return "", 0, 0, false
	}

	res.CountryCode = strings.ToUpper(strings.TrimSpace(res.CountryCode))
	if res.Lat < -90 || res.Lat > 90 || res.Lon < -180 || res.Lon > 180 {
		cacheGeo(host, nil)
		return "", 0, 0, false
	}

	cacheGeo(host, &res)
	return res.CountryCode, res.Lat, res.Lon, true
}

func cacheGeo(host string, data *GeoResult) {
	geoCacheMu.Lock()
	defer geoCacheMu.Unlock()
	// Cache successful or negative lookups for 1 hour to prevent flooding
	geoCache[host] = geoCacheEntry{
		data:      data,
		expiresAt: time.Now().Add(time.Hour),
	}
}

func extractHost(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}
	if parsed := net.ParseIP(raw); parsed != nil {
		return parsed.String()
	}
	candidate := raw
	if !strings.Contains(candidate, "://") {
		candidate = "//" + candidate
	}
	u, err := url.Parse(candidate)
	if err != nil {
		return ""
	}
	h := u.Hostname()
	return strings.Trim(h, "[]")
}

func resolveIP(host string) string {
	if parsed := net.ParseIP(host); parsed != nil {
		return parsed.String()
	}
	ips, err := net.LookupIP(host)
	if err != nil || len(ips) == 0 {
		return ""
	}
	for _, ip := range ips {
		if ipv4 := ip.To4(); ipv4 != nil {
			return ipv4.String()
		}
	}
	return ips[0].String()
}
