// Package metrics renders the live state of the command center in the
// Prometheus text exposition format, so Grafana can chart and alert on the same
// numbers the REST API serves.
//
// The encoder is hand-rolled on purpose. The whole service has exactly one
// dependency; a scrape endpoint that boils down to printing floats with labels
// is not worth a second one — and it keeps `go build` working offline.
package metrics

import (
	"io"
	"math"
	"sort"
	"strconv"
	"strings"
)

// ContentType is the media type of the exposition format written here. It is
// what Prometheus expects from a scrape target.
const ContentType = "text/plain; version=0.0.4; charset=utf-8"

// Label is one metric dimension. Keep the value set small and bounded —
// every distinct combination is a separate time series in Prometheus.
type Label struct {
	Name  string
	Value string
}

// sample is one line of the exposition: metric name + suffix, labels, value.
type sample struct {
	suffix string // "", or "_bucket" / "_sum" / "_count" for histograms
	labels []Label
	value  float64
}

// family groups all samples that share a name, HELP and TYPE.
type family struct {
	name    string
	typ     string
	help    string
	samples []sample
}

// add appends a plain sample to the family.
func (f *family) add(value float64, labels ...Label) {
	f.samples = append(f.samples, sample{labels: labels, value: value})
}

// addSuffixed appends a sample under a name suffix. Only histograms need it.
func (f *family) addSuffixed(suffix string, value float64, labels ...Label) {
	f.samples = append(f.samples, sample{suffix: suffix, labels: labels, value: value})
}

// registry collects metric families in declaration order. Samples of one family
// always render together, which is what the text format requires — asking for
// the same family twice returns the existing one instead of emitting a second
// HELP/TYPE block.
type registry struct {
	order  []string
	byName map[string]*family
}

func newRegistry() *registry {
	return &registry{byName: make(map[string]*family)}
}

// metric declares (or looks up) a family. typ is "counter", "gauge" or
// "histogram".
func (r *registry) metric(name, typ, help string) *family {
	if f, ok := r.byName[name]; ok {
		return f
	}
	f := &family{name: name, typ: typ, help: help}
	r.byName[name] = f
	r.order = append(r.order, name)
	return f
}

// WriteTo renders every family. Families with no samples are skipped entirely —
// a HELP block without data only confuses the scraper.
func (r *registry) WriteTo(w io.Writer) (int64, error) {
	var sb strings.Builder
	for _, name := range r.order {
		f := r.byName[name]
		if len(f.samples) == 0 {
			continue
		}
		sb.WriteString("# HELP ")
		sb.WriteString(f.name)
		sb.WriteByte(' ')
		sb.WriteString(escapeHelp(f.help))
		sb.WriteByte('\n')

		sb.WriteString("# TYPE ")
		sb.WriteString(f.name)
		sb.WriteByte(' ')
		sb.WriteString(f.typ)
		sb.WriteByte('\n')

		for _, s := range f.samples {
			sb.WriteString(f.name)
			sb.WriteString(s.suffix)
			writeLabels(&sb, s.labels)
			sb.WriteByte(' ')
			sb.WriteString(formatValue(s.value))
			sb.WriteByte('\n')
		}
	}
	n, err := io.WriteString(w, sb.String())
	return int64(n), err
}

// writeLabels renders `{a="1",b="2"}`, or nothing when there are no labels.
// Labels with an empty value are dropped: an absent account id should not
// create a second time series next to the named one.
func writeLabels(sb *strings.Builder, labels []Label) {
	first := true
	for _, l := range labels {
		if l.Value == "" {
			continue
		}
		if first {
			sb.WriteByte('{')
			first = false
		} else {
			sb.WriteByte(',')
		}
		sb.WriteString(l.Name)
		sb.WriteString(`="`)
		sb.WriteString(escapeLabelValue(l.Value))
		sb.WriteByte('"')
	}
	if !first {
		sb.WriteByte('}')
	}
}

// formatValue prints a float the way the exposition format wants it, including
// the three special values Go's formatter spells differently.
func formatValue(v float64) string {
	switch {
	case math.IsNaN(v):
		return "NaN"
	case math.IsInf(v, 1):
		return "+Inf"
	case math.IsInf(v, -1):
		return "-Inf"
	default:
		return strconv.FormatFloat(v, 'g', -1, 64)
	}
}

func escapeLabelValue(s string) string {
	if !strings.ContainsAny(s, `\"`+"\n") {
		return s
	}
	r := strings.NewReplacer(`\`, `\\`, `"`, `\"`, "\n", `\n`)
	return r.Replace(s)
}

func escapeHelp(s string) string {
	if !strings.ContainsAny(s, `\`+"\n") {
		return s
	}
	r := strings.NewReplacer(`\`, `\\`, "\n", `\n`)
	return r.Replace(s)
}

// sortedKeys returns the keys of a map in a stable order. Scrape output must not
// reshuffle between requests — it makes diffing a scrape impossible and upsets
// strict parsers that expect one family's samples to stay together.
func sortedKeys[K comparable, V any](m map[K]V, less func(a, b K) bool) []K {
	keys := make([]K, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool { return less(keys[i], keys[j]) })
	return keys
}
