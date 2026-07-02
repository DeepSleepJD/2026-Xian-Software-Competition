package org.lychee.basicclient.tests;

import org.lychee.basicclient.JsonFields;
import org.lychee.basicclient.Messages;

public final class BasicJavaClientPublicApiTest {
    private BasicJavaClientPublicApiTest() {
    }

    public static void main(String[] args) {
        testMoveActionUsesTargetNodeId();
        testEscapesAndReadsUnicodeText();
        testReadsEscapedJsonString();
    }

    private static void testMoveActionUsesTargetNodeId() {
        String json = Messages.moveAction("match-1", 7, 1004, "S10");
        assertEquals("{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"match-1\","
                + "\"round\":7,\"playerId\":1004,\"actions\":[{\"action\":\"MOVE\","
                + "\"targetNodeId\":\"S10\"}]}}", json);
    }

    private static void testEscapesAndReadsUnicodeText() {
        String escaped = JsonFields.escape("荔枝🚚\n\"");
        assertEquals("荔枝🚚\\n\\\"", escaped);
    }

    private static void testReadsEscapedJsonString() {
        String json = "{\"msg_data\":{\"playerName\":\"\\u8354\\u679d\\nAgent\\\"A\\\"\"}}";
        String data = JsonFields.extractObjectField(json, "msg_data");

        assertEquals("荔枝\nAgent\"A\"", JsonFields.extractDirectStringField(data, "playerName"));
    }

    private static void assertEquals(String expected, String actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError("expected <" + expected + "> but got <" + actual + ">");
        }
    }
}
