package server

import (
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"

	"github.com/open-lambda/open-lambda/ol/common"
	"github.com/open-lambda/open-lambda/ol/worker/lambda"
)

// connReqs lets Max_conn_requests be enforced per connection, keyed by RemoteAddr. An entry is
// removed only at the limit, so a connection closed earlier leaves its count behind for the next
// one on the same address and port.
var connReqs sync.Map

// closeIfSpent closes the connection after Max_conn_requests requests or, under Close_when_busy,
// when nothing idle can serve the request, so the scheduler chooses a worker again.
func closeIfSpent(w http.ResponseWriter, r *http.Request) {
	busy := false
	if common.Conf.Close_when_busy {
		parts := getURLComponents(r)
		busy = len(parts) >= 2 && lambda.SigIdle(parts[1]) == 0
	}

	max := common.Conf.Max_conn_requests
	if max > 0 {
		v, _ := connReqs.LoadOrStore(r.RemoteAddr, new(int32))
		if atomic.AddInt32(v.(*int32), 1) >= int32(max) {
			connReqs.Delete(r.RemoteAddr)
			busy = true
		}
	}
	if busy {
		w.Header().Set("Connection", "close")
	}
}

// LambdaServer is a worker server that listens to run lambda requests and forward
// these requests to its sandboxes.
type LambdaServer struct {
	lambdaMgr *lambda.LambdaMgr
}

// getURLComponents parses request URL into its "/" delimated components
func getURLComponents(r *http.Request) []string {
	path := r.URL.Path

	// trim prefix
	if strings.HasPrefix(path, "/") {
		path = path[1:]
	}

	// trim trailing "/"
	if strings.HasSuffix(path, "/") {
		path = path[:len(path)-1]
	}

	components := strings.Split(path, "/")
	return components
}

// RunLambda expects POST requests like this:
//
// curl localhost:8080/run/<lambda-name>
// curl -X POST localhost:8080/run/<lambda-name> -d '{}'
// ...
func (s *LambdaServer) RunLambda(w http.ResponseWriter, r *http.Request) {
	t := common.T0("web-request")
	defer t.T1()

	closeIfSpent(w, r)

	// TODO re-enable logging once it is configurable
	// log.Printf("Received request to %s\n", r.URL.Path)

	// components represent run[0]/<name_of_sandbox>[1]/<extra_things>...
	// ergo we want [1] for name of sandbox
	urlParts := getURLComponents(r)
	if len(urlParts) < 2 {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte("expected invocation format: /run/<lambda-name>"))
	} else {
		// components represent run[0]/<name_of_sandbox>[1]/<extra_things>...
		// ergo we want [1] for name of sandbox
		urlParts := getURLComponents(r)
		if len(urlParts) == 2 {
			img := urlParts[1]
			s.lambdaMgr.Get(img).Invoke(w, r)
		} else {
			w.WriteHeader(http.StatusInternalServerError)
			w.Write([]byte("expected invocation format: /run/<lambda-name>"))
		}
	}
}

func (s *LambdaServer) Debug(w http.ResponseWriter, _ *http.Request) {
	w.Write([]byte(s.lambdaMgr.Debug()))
}

func (s *LambdaServer) cleanup() {
	s.lambdaMgr.Cleanup()
}

// NewLambdaServer creates a server based on the passed config."
func NewLambdaServer() (*LambdaServer, error) {
	log.Printf("Starting new lambda server")

	lambdaMgr, err := lambda.NewLambdaMgr()
	if err != nil {
		return nil, err
	}

	server := &LambdaServer{
		lambdaMgr: lambdaMgr,
	}

	log.Printf("Setups Handlers")
	port := fmt.Sprintf(":%s", common.Conf.Worker_port)
	http.HandleFunc(RUN_PATH, server.RunLambda)
	http.HandleFunc(DEBUG_PATH, server.Debug)

	log.Printf("Execute handler by POSTing to %s%s%s%s\n", common.Conf.Worker_url, port, RUN_PATH, "<lambda>")
	log.Printf("Get status by sending request to %s%s%s\n", common.Conf.Worker_url, port, STATUS_PATH)

	return server, nil
}
