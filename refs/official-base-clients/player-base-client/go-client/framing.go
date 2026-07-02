package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"strconv"
)

const maxBody = 99999

func readFrame(conn net.Conn) ([]byte, error) {
	prefix := make([]byte, 5)
	if _, err := io.ReadFull(conn, prefix); err != nil {
		return nil, err
	}
	length, err := strconv.Atoi(string(prefix))
	if err != nil {
		return nil, fmt.Errorf("invalid frame prefix %q: %w", string(prefix), err)
	}
	if length < 0 || length > maxBody {
		return nil, fmt.Errorf("invalid frame length: %d", length)
	}
	body := make([]byte, length)
	if _, err := io.ReadFull(conn, body); err != nil {
		return nil, err
	}
	return body, nil
}

func writeJSONFrame(conn net.Conn, value any) error {
	body, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if len(body) > maxBody {
		return fmt.Errorf("message too large: %d", len(body))
	}
	prefix := fmt.Sprintf("%05d", len(body))
	if err := writeAll(conn, []byte(prefix)); err != nil {
		return err
	}
	return writeAll(conn, body)
}

func writeAll(conn net.Conn, data []byte) error {
	for len(data) > 0 {
		written, err := conn.Write(data)
		if err != nil {
			return err
		}
		if written == 0 {
			return io.ErrShortWrite
		}
		data = data[written:]
	}
	return nil
}
