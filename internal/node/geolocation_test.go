// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestGeolocateValidIP(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"success","countryCode":"DE","lat":49.45,"lon":11.07}`)
	}))
	defer ts.Close()

	oldURL := geolocateBaseURL
	geolocateBaseURL = ts.URL
	defer func() { geolocateBaseURL = oldURL }()

	cc, lat, lon, ok := Geolocate("203.0.113.1")
	if !ok {
		t.Fatal("expected geolocate ok = true")
	}
	if cc != "DE" {
		t.Errorf("expected DE, got %s", cc)
	}
	if lat != 49.45 || lon != 11.07 {
		t.Errorf("unexpected coords: %f, %f", lat, lon)
	}
}

func TestGeolocateInvalidIP(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"fail","message":"private range"}`)
	}))
	defer ts.Close()

	oldURL := geolocateBaseURL
	geolocateBaseURL = ts.URL
	defer func() { geolocateBaseURL = oldURL }()

	_, _, _, ok := Geolocate("10.0.0.1")
	if ok {
		t.Fatal("expected geolocate ok = false for private range")
	}
}
