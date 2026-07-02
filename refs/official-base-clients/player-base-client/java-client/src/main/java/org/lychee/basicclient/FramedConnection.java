package org.lychee.basicclient;

import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

public final class FramedConnection {
    private static final int MAX_BODY = 99999;

    private final InputStream input;
    private final OutputStream output;

    public FramedConnection(InputStream input, OutputStream output) {
        this.input = input;
        this.output = output;
    }

    public String read() throws IOException {
        byte[] prefix = readExactly(5);
        int length = Integer.parseInt(new String(prefix, StandardCharsets.US_ASCII));
        if (length < 0 || length > MAX_BODY) {
            throw new IOException("invalid frame length: " + length);
        }
        byte[] body = readExactly(length);
        return new String(body, StandardCharsets.UTF_8);
    }

    public void write(String json) throws IOException {
        byte[] body = json.getBytes(StandardCharsets.UTF_8);
        if (body.length > MAX_BODY) {
            throw new IOException("message too large: " + body.length);
        }
        String prefix = String.format("%05d", body.length);
        output.write(prefix.getBytes(StandardCharsets.US_ASCII));
        output.write(body);
        output.flush();
    }

    private byte[] readExactly(int length) throws IOException {
        byte[] buffer = new byte[length];
        int offset = 0;
        while (offset < length) {
            int read = input.read(buffer, offset, length - offset);
            if (read < 0) {
                throw new EOFException();
            }
            offset += read;
        }
        return buffer;
    }
}
