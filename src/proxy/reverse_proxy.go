package proxy

import (
	"net/http"
	"net/http/httputil"
	"net/url"
	"sync"
	"time"
)

// ReverseProxy is an interface for an object that proxies the client HTTP
// request to a worker. The implementation is free to choose any
// protocol or network stack
type ReverseProxy interface {
	// ProxyRequest is a function that proxies the client HTTP request to a
	// worker. It takes the same parameters as an HTTP server handler along
	// with the worker as the first parameter. It is expected to send a
	// response to the client using the ResponseWriter object.
	ProxyRequest(workerURL url.URL, w http.ResponseWriter, r *http.Request)
}

// workerTransport keeps up to 1024 idle connections per worker: net/http's default keeps 2, so
// under load the proxy opens a fresh TCP connection per request and exhausts the ephemeral ports.
var workerTransport = &http.Transport{
	MaxIdleConns:        4096,
	MaxIdleConnsPerHost: 1024,
	IdleConnTimeout:     90 * time.Second,
}

type HTTPReverseProxy struct {
	proxyMap map[url.URL]*httputil.ReverseProxy
	mutex    sync.Mutex
}

func (p *HTTPReverseProxy) getReverseProxyForWorker(workerURL url.URL) *httputil.ReverseProxy {
	p.mutex.Lock()
	defer p.mutex.Unlock()

	proxy := p.proxyMap[workerURL]
	if proxy == nil {
		proxy = httputil.NewSingleHostReverseProxy(&workerURL)
		proxy.Transport = workerTransport
		p.proxyMap[workerURL] = proxy
	}

	return proxy
}

func (p *HTTPReverseProxy) ProxyRequest(workerURL url.URL, w http.ResponseWriter, r *http.Request) {
	proxy := p.getReverseProxyForWorker(workerURL)
	proxy.ServeHTTP(w, r)
}

func NewHTTPReverseProxy() ReverseProxy {
	return &HTTPReverseProxy{
		proxyMap: make(map[url.URL]*httputil.ReverseProxy),
		mutex:    sync.Mutex{},
	}
}
