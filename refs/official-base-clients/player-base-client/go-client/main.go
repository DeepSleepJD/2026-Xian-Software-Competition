package main

import (
	"errors"
	"fmt"
	"net"
	"os"
	"strconv"
)

func main() {
	cfg := parseFlags()
	conn, err := net.Dial("tcp", net.JoinHostPort(cfg.host, strconv.Itoa(cfg.port)))
	if err != nil {
		fail(err)
	}
	defer conn.Close()

	fmt.Printf("connected to %s:%d as player %d\n", cfg.host, cfg.port, cfg.playerID)
	if err := newClient(conn, cfg).run(); errors.Is(err, errServerMessage) {
		os.Exit(1)
	} else if err != nil {
		fail(err)
	}
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
