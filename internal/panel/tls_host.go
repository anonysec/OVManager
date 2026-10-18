// Host identity detection: which name or IP the panel is reachable under, for
// a fresh self-signed certificate and for IP-based ACME orders.
package panel

import (
	"net"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"
)

func (h *Handler) configuredIdentity(s settings) string {
	if envDomain := strings.TrimSpace(envFileValues()["ACME_DOMAIN"]); envDomain != "" {
		return envDomain
	}
	if domain := strings.TrimSpace(s.strOr("acme_domain")); domain != "" {
		return domain
	}
	return storedPublicIP()
}

func (h *Handler) primaryIdentity() string {
	if v := h.configuredIdentity(h.settings()); v != "" {
		return v
	}
	if v := installerPublicIP(); v != "" {
		return v
	}
	return detectPrimaryIP()
}

func primaryIP() string {
	if v := storedPublicIP(); v != "" {
		return v
	}
	if v := installerPublicIP(); v != "" {
		return v
	}
	return detectPrimaryIP()
}

// storedPublicIP is the literal address in PUBLIC_URL, when there is one.
func storedPublicIP() string {
	raw := strings.TrimSpace(envOrFile("PUBLIC_URL"))
	if raw == "" {
		return ""
	}
	if !strings.Contains(raw, "://") {
		raw = "//" + raw
	}
	host := raw
	if i := strings.Index(host, "://"); i >= 0 {
		host = host[i+3:]
	}
	if i := strings.IndexAny(host, "/?#"); i >= 0 {
		host = host[:i]
	}
	if h, _, err := net.SplitHostPort(host); err == nil {
		host = h
	}
	if ip := net.ParseIP(host); ip != nil {
		return ip.String()
	}
	return ""
}

// detectPrimaryIP is _detect_primary_ip: routable IPv4 first, then hostname.
func detectPrimaryIP() string {
	routable := ""
	if out, err := exec.Command("hostname", "-I").Output(); err == nil {
		for _, token := range strings.Fields(string(out)) {
			addr := net.ParseIP(token)
			if addr == nil || addr.To4() == nil {
				continue
			}
			if !addr.IsPrivate() && !addr.IsLoopback() && !addr.IsLinkLocalUnicast() {
				return addr.String()
			}
			if routable == "" && !addr.IsLoopback() && !addr.IsLinkLocalUnicast() {
				routable = addr.String()
			}
		}
	}
	if routable != "" {
		return routable
	}
	if addrs, err := net.LookupHost(hostnameOrEmpty()); err == nil && len(addrs) > 0 {
		return addrs[0]
	}
	return "127.0.0.1"
}

func hostnameOrEmpty() string {
	name, err := os.Hostname()
	if err != nil {
		return "localhost"
	}
	return name
}

// installerPublicIP asks the same two services install.sh's public_ip() asks.
func installerPublicIP() string {
	client := &http.Client{Timeout: 3 * time.Second}
	for _, url := range []string{"https://api.ipify.org", "https://ifconfig.me/ip"} {
		resp, err := client.Get(url)
		if err != nil {
			continue
		}
		raw, err := readAtMost(resp.Body, 64)
		resp.Body.Close()
		if err != nil {
			continue
		}
		text := strings.TrimSpace(string(raw))
		if text != "" && strings.Trim(text, "0123456789abcdefABCDEF.:") == "" {
			return text
		}
	}
	// No egress: fall back to detection rather than sending a bad name to LE.
	return ""
}
