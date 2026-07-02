package org.lychee.basicclient;

import java.io.EOFException;
import java.io.IOException;

public final class ClientSession {
    private final Config config;
    private final FramedConnection connection;
    private String matchId = "";

    public ClientSession(Config config, FramedConnection connection) {
        this.config = config;
        this.connection = connection;
    }

    public void run() throws IOException {
        connection.write(Messages.registration(config));
        while (true) {
            String frame = readNextFrame();
            if (frame == null) {
                return;
            }
            if (!handleFrame(frame)) {
                return;
            }
        }
    }

    private String readNextFrame() throws IOException {
        try {
            return connection.read();
        } catch (EOFException ex) {
            System.out.println("connection closed");
            return null;
        }
    }

    private boolean handleFrame(String frame) throws IOException {
        String msgName = JsonFields.extractStringField(frame, "msg_name");
        String msgData = JsonFields.extractObjectField(frame, "msg_data");
        if ("start".equals(msgName)) {
            handleStart(msgData);
        } else if ("inquire".equals(msgName)) {
            handleInquire(msgData);
        } else if ("over".equals(msgName)) {
            System.out.println("over received");
            return false;
        } else if ("error".equals(msgName)) {
            System.err.println("error received: " + frame);
            System.exit(1);
        } else {
            System.out.println("ignored msg_name=" + msgName);
        }
        return true;
    }

    private void handleStart(String msgData) throws IOException {
        matchId = JsonFields.extractDirectStringField(msgData, "matchId");
        int round = JsonFields.extractDirectIntField(msgData, "round", 1);
        System.out.printf("start match=%s round=%d%n", matchId, round);
        connection.write(Messages.ready(matchId, round, config.playerId()));
    }

    private void handleInquire(String msgData) throws IOException {
        int round = JsonFields.extractDirectIntField(msgData, "round", 0);
        System.out.printf("inquire round=%d -> heartbeat%n", round);
        connection.write(Messages.heartbeatAction(matchId, round, config.playerId()));
    }
}
