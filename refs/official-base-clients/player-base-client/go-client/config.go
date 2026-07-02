package main

import "flag"

type config struct {
	host       string
	port       int
	playerID   int
	playerName string
	version    string
}

func parseFlags() config {
	var cfg config
	flag.StringVar(&cfg.host, "host", "127.0.0.1", "arena server host")
	flag.IntVar(&cfg.port, "port", 30000, "arena server port")
	flag.IntVar(&cfg.playerID, "player-id", 1003, "contest player ID")
	flag.StringVar(&cfg.playerName, "player-name", "BasicGo", "contest player name")
	flag.StringVar(&cfg.version, "version", "0.1", "client version")
	flag.Parse()
	return cfg
}
