package org.lychee.basicclient;

import java.net.Socket;

public final class BasicJavaClient {
    private BasicJavaClient() {
    }

    public static void main(String[] args) throws Exception {
        Config config = Config.parse(args);
        try (Socket socket = new Socket(config.host(), config.port())) {
            System.out.printf("connected to %s:%d as player %d%n",
                    config.host(), config.port(), config.playerId());
            FramedConnection connection = new FramedConnection(socket.getInputStream(), socket.getOutputStream());
            new ClientSession(config, connection).run();
        }
    }
}
