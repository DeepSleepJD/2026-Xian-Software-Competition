package org.lychee.basicclient;

import java.util.Arrays;

public final class Config {
    private String host = "127.0.0.1";
    private int port = 30000;
    private int playerId = 1004;
    private String playerName = "BasicJava";
    private String version = "0.1";

    public String host() {
        return host;
    }

    public int port() {
        return port;
    }

    public int playerId() {
        return playerId;
    }

    public String playerName() {
        return playerName;
    }

    public String version() {
        return version;
    }

    public static Config parse(String[] args) {
        Config config = new Config();
        for (int i = 0; i < args.length; i++) {
            String arg = args[i];
            if ("--host".equals(arg)) {
                config.host = requireValue(args, ++i, arg);
            } else if ("--port".equals(arg)) {
                config.port = Integer.parseInt(requireValue(args, ++i, arg));
            } else if ("--player-id".equals(arg)) {
                config.playerId = Integer.parseInt(requireValue(args, ++i, arg));
            } else if ("--player-name".equals(arg)) {
                config.playerName = requireValue(args, ++i, arg);
            } else if ("--version".equals(arg)) {
                config.version = requireValue(args, ++i, arg);
            } else if ("--help".equals(arg)) {
                printUsageAndExit();
            } else {
                System.err.println("unknown argument: " + arg);
                printUsageAndExit();
            }
        }
        return config;
    }

    private static String requireValue(String[] args, int index, String name) {
        if (index >= args.length) {
            throw new IllegalArgumentException("missing value for " + name + ": " + Arrays.toString(args));
        }
        return args[index];
    }

    private static void printUsageAndExit() {
        System.out.println("Usage: java -jar target/lychee-basic-java-client-0.1.0.jar "
                + "[--host HOST] [--port PORT] [--player-id ID] "
                + "[--player-name NAME] [--version VERSION]");
        System.exit(0);
    }
}
