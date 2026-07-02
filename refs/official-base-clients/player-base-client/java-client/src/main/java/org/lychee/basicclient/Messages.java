package org.lychee.basicclient;

public final class Messages {
    private Messages() {
    }

    public static String registration(Config config) {
        return "{\"msg_name\":\"registration\",\"msg_data\":{\"playerId\":" + config.playerId()
                + ",\"playerName\":\"" + JsonFields.escape(config.playerName())
                + "\",\"version\":\"" + JsonFields.escape(config.version()) + "\"}}";
    }

    public static String ready(String matchId, int round, int playerId) {
        return "{\"msg_name\":\"ready\",\"msg_data\":{\"matchId\":\"" + JsonFields.escape(matchId)
                + "\",\"round\":" + round + ",\"playerId\":" + playerId + "}}";
    }

    public static String heartbeatAction(String matchId, int round, int playerId) {
        return "{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"" + JsonFields.escape(matchId)
                + "\",\"round\":" + round + ",\"playerId\":" + playerId + ",\"actions\":[]}}";
    }

    public static String moveAction(String matchId, int round, int playerId, String targetNodeId) {
        return "{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"" + JsonFields.escape(matchId)
                + "\",\"round\":" + round + ",\"playerId\":" + playerId
                + ",\"actions\":[{\"action\":\"MOVE\",\"targetNodeId\":\""
                + JsonFields.escape(targetNodeId) + "\"}]}}";
    }
}
