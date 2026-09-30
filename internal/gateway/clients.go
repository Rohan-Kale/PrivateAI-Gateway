package gateway

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"
)

const maxResponse = 256 * 1024

type HTTPDetector struct {
	URL    string
	Key    string
	Client *http.Client
}

func (d HTTPDetector) Detect(ctx context.Context, text string) ([]Span, error) {
	b, _ := json.Marshal(map[string]string{"text": text})
	r, e := http.NewRequestWithContext(ctx, "POST", d.URL+"/detect", bytes.NewReader(b))
	if e != nil {
		return nil, e
	}
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Authorization", "Bearer "+d.Key)
	resp, e := d.Client.Do(r)
	if e != nil {
		return nil, errors.New("detector unavailable")
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, errors.New("detector rejected request")
	}
	raw, e := io.ReadAll(io.LimitReader(resp.Body, maxResponse+1))
	if e != nil || len(raw) > maxResponse {
		return nil, errors.New("invalid detector response")
	}
	var data struct {
		Spans []Span `json:"spans"`
	}
	if e = json.Unmarshal(raw, &data); e != nil {
		return nil, errors.New("invalid detector response")
	}
	return data.Spans, nil
}

type HTTPProvider struct {
	URL    string
	Key    string
	Client *http.Client
}

func (p HTTPProvider) Infer(ctx context.Context, req Request) (string, error) {
	b, _ := json.Marshal(req)
	r, e := http.NewRequestWithContext(ctx, "POST", p.URL+"/v1/chat/completions", bytes.NewReader(b))
	if e != nil {
		return "", e
	}
	r.Header.Set("Content-Type", "application/json")
	if p.Key != "" {
		r.Header.Set("Authorization", "Bearer "+p.Key)
	}
	resp, e := p.Client.Do(r)
	if e != nil {
		return "", errors.New("provider unavailable")
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", errors.New("provider rejected request")
	}
	if req.Stream {
		return collectSSE(resp.Body)
	}
	raw, e := io.ReadAll(io.LimitReader(resp.Body, maxResponse+1))
	if e != nil || len(raw) > maxResponse {
		return "", errors.New("provider response too large")
	}
	var data struct {
		Choices []struct {
			Message Message `json:"message"`
		} `json:"choices"`
	}
	if e = json.Unmarshal(raw, &data); e != nil || len(data.Choices) != 1 {
		return "", errors.New("invalid provider response")
	}
	if !utf8.ValidString(data.Choices[0].Message.Content) {
		return "", errors.New("invalid provider UTF-8")
	}
	return data.Choices[0].Message.Content, nil
}
func collectSSE(reader io.Reader) (string, error) {
	scan := bufio.NewScanner(io.LimitReader(reader, 2*maxResponse+1))
	scan.Buffer(make([]byte, 4096), maxResponse)
	var b strings.Builder
	for scan.Scan() {
		line := scan.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if data == "[DONE]" {
			return b.String(), nil
		}
		var frame struct {
			Choices []struct {
				Delta struct {
					Content string `json:"content"`
				} `json:"delta"`
			} `json:"choices"`
		}
		if json.Unmarshal([]byte(data), &frame) != nil || len(frame.Choices) != 1 {
			return "", errors.New("invalid provider stream")
		}
		b.WriteString(frame.Choices[0].Delta.Content)
		if b.Len() > maxResponse {
			return "", errors.New("provider response too large")
		}
	}
	return "", errors.New("provider stream interrupted")
}
func NewHTTPClient() *http.Client {
	return &http.Client{Timeout: 50 * time.Second, Transport: &http.Transport{MaxIdleConns: 256, MaxIdleConnsPerHost: 128, MaxConnsPerHost: 256, IdleConnTimeout: 90 * time.Second}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}
