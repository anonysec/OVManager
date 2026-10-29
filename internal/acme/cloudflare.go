package acme

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type cfCreds struct {
	token string
	email string
	key   string
}

func cfHeaders(o Options) (cfCreds, *http.Client) {
	return cfCreds{token: o.CFToken, email: o.CFEmail, key: o.CFKey}, &http.Client{Timeout: 30 * time.Second}
}

func cfAuthHeaders(c cfCreds, req *http.Request) {
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	} else {
		req.Header.Set("X-Auth-Email", c.email)
		req.Header.Set("X-Auth-Key", c.key)
	}
	req.Header.Set("Content-Type", "application/json")
}

func cfZoneID(creds cfCreds, client *http.Client, domain string) (string, error) {
	// try the domain, then parents
	labels := strings.Split(domain, ".")
	for i := 0; i < len(labels)-1; i++ {
		candidate := strings.Join(labels[i:], ".")
		url := "https://api.cloudflare.com/client/v4/zones?name=" + candidate
		req, _ := http.NewRequest("GET", url, nil)
		cfAuthHeaders(creds, req)
		resp, err := client.Do(req)
		if err != nil {
			return "", err
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		var r struct {
			Success bool `json:"success"`
			Result  []struct {
				ID   string `json:"id"`
				Name string `json:"name"`
			} `json:"result"`
		}
		if err := json.Unmarshal(body, &r); err != nil {
			return "", err
		}
		if r.Success && len(r.Result) > 0 {
			return r.Result[0].ID, nil
		}
	}
	return "", fmt.Errorf("cloudflare: zone not found for %s", domain)
}

func cfCreateTXT(o Options, domain, value string) (string, error) {
	creds, client := cfHeaders(o)
	zoneID, err := cfZoneID(creds, client, domain)
	if err != nil {
		return "", err
	}
	name := "_acme-challenge." + domain
	payload := map[string]any{
		"type":    "TXT",
		"name":    name,
		"content": value,
		"ttl":     120,
	}
	b, _ := json.Marshal(payload)
	url := fmt.Sprintf("https://api.cloudflare.com/client/v4/zones/%s/dns_records", zoneID)
	req, _ := http.NewRequest("POST", url, bytes.NewReader(b))
	cfAuthHeaders(creds, req)
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	var r struct {
		Success bool `json:"success"`
		Result  struct {
			ID string `json:"id"`
		} `json:"result"`
		Errors []struct {
			Message string `json:"message"`
		} `json:"errors"`
	}
	if err := json.Unmarshal(body, &r); err != nil {
		return "", err
	}
	if !r.Success {
		msg := "unknown error"
		if len(r.Errors) > 0 {
			msg = r.Errors[0].Message
		}
		return "", fmt.Errorf("cloudflare: create record: %s", msg)
	}
	return r.Result.ID, nil
}

func cfDeleteTXT(o Options, domain, recordID string) error {
	creds, client := cfHeaders(o)
	zoneID, err := cfZoneID(creds, client, domain)
	if err != nil {
		return err
	}
	url := fmt.Sprintf("https://api.cloudflare.com/client/v4/zones/%s/dns_records/%s", zoneID, recordID)
	req, _ := http.NewRequest("DELETE", url, nil)
	cfAuthHeaders(creds, req)
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	resp.Body.Close()
	return nil
}
