package main

import (
	"encoding/json"
	"net"
	"testing"
)

func TestWriteAndReadFrame(t *testing.T) {
	left, right := net.Pipe()
	defer left.Close()
	defer right.Close()

	errs := make(chan error, 1)
	go func() {
		errs <- writeJSONFrame(left, map[string]any{"msg_name": "ping"})
	}()

	body, err := readFrame(right)
	if err != nil {
		t.Fatalf("readFrame failed: %v", err)
	}
	if err := <-errs; err != nil {
		t.Fatalf("writeJSONFrame failed: %v", err)
	}

	var got map[string]any
	if err := json.Unmarshal(body, &got); err != nil {
		t.Fatalf("body is not valid JSON: %v", err)
	}
	if got["msg_name"] != "ping" {
		t.Fatalf("msg_name = %v, want ping", got["msg_name"])
	}
}
