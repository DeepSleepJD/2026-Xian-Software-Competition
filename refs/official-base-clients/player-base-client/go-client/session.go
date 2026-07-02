package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
)

var errServerMessage = errors.New("server returned error")

type client struct {
	conn    net.Conn
	config  config
	matchID string
}

func newClient(conn net.Conn, cfg config) *client {
	return &client{conn: conn, config: cfg}
}

func (client *client) run() error {
	if err := client.sendRegistration(); err != nil {
		return err
	}

	for {
		body, err := readFrame(client.conn)
		if err == io.EOF {
			fmt.Println("connection closed")
			return nil
		}
		if err != nil {
			return err
		}

		shouldContinue, err := client.handleFrame(body)
		if err != nil || !shouldContinue {
			return err
		}
	}
}

func (client *client) sendRegistration() error {
	return writeJSONFrame(client.conn, registrationMessage(client.config))
}

func (client *client) handleFrame(body []byte) (bool, error) {
	var msg envelope
	if err := json.Unmarshal(body, &msg); err != nil {
		return false, err
	}

	switch msg.MsgName {
	case "start":
		return true, client.handleStart(msg.MsgData)
	case "inquire":
		return true, client.handleInquire(msg.MsgData)
	case "over":
		fmt.Println("over received")
		return false, nil
	case "error":
		fmt.Fprintf(os.Stderr, "error received: %s\n", string(body))
		return false, errServerMessage
	default:
		fmt.Printf("ignored msg_name=%s\n", msg.MsgName)
		return true, nil
	}
}

func (client *client) handleStart(rawData json.RawMessage) error {
	var data startData
	if err := json.Unmarshal(rawData, &data); err != nil {
		return err
	}
	client.matchID = data.MatchID
	fmt.Printf("start match=%s round=%d\n", client.matchID, data.Round)
	return writeJSONFrame(client.conn, readyMessage(client.matchID, data.Round, client.config.playerID))
}

func (client *client) handleInquire(rawData json.RawMessage) error {
	var data inquireData
	if err := json.Unmarshal(rawData, &data); err != nil {
		return err
	}
	fmt.Printf("inquire round=%d -> heartbeat\n", data.Round)
	return writeJSONFrame(client.conn, heartbeatAction(client.matchID, data.Round, client.config.playerID))
}
