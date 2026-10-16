package balancer

import (
	"container/heap"
	"hash/fnv"
	"net/http"
	"net/url"

	"hiku/httputil"
	"hiku/lambda"
)

// PullOrdered is PullBased with another choice among the idle workers: the first one in the
// function's own hash order instead of the least loaded one, so a function stays on as few
// workers as its load needs.
type PullOrdered struct {
	*PullBased
}

func (b *PullOrdered) SelectWorker(r *http.Request, l *lambda.Lambda) (url.URL, *httputil.HttpError) {
	b.mutex.Lock()
	defer b.mutex.Unlock()

	n := len(b.workerUrls)
	if n == 0 {
		return b.selectLeastLoadedWorker()
	}
	hash := fnv.New32a()
	hash.Write([]byte(l.Name))
	start := int(hash.Sum32() % uint32(n))

	queue := b.getIdleQueue(l.Name)
	first, firstRank := -1, n
	for i, item := range *queue {
		index := FindUrlInSlice(b.workerUrls, item.url)
		if index == -1 {
			continue
		}
		rank := (index + n - start) % n
		if rank < firstRank {
			first, firstRank = i, rank
		}
	}

	if first != -1 {
		workerURL := heap.Remove(queue, first).(*Item).url
		b.incrementWorkerLoad(workerURL)
		return workerURL, nil
	}

	return b.selectLeastLoadedWorker()
}

func NewPullOrderedFromJSONSlice(jsonSlice []string) Balancer {
	return &PullOrdered{NewPullBased(CreateWorkerURLSlice(jsonSlice)).(*PullBased)}
}
