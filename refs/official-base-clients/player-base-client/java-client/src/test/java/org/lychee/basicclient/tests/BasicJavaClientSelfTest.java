package org.lychee.basicclient.tests;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import org.lychee.basicclient.FramedConnection;
import org.lychee.basicclient.Messages;

public final class BasicJavaClientSelfTest {
    private BasicJavaClientSelfTest() {
    }

    public static void main(String[] args) throws Exception {
        testWriteFrame();
        testReadFrame();
        testHeartbeatAction();
        BasicJavaClientPublicApiTest.main(args);
    }

    private static void testWriteFrame() throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        FramedConnection connection = new FramedConnection(new ByteArrayInputStream(new byte[0]), output);

        connection.write("{\"msg_name\":\"ping\"}");

        assertEquals("00019{\"msg_name\":\"ping\"}", output.toString(StandardCharsets.UTF_8));
    }

    private static void testReadFrame() throws Exception {
        byte[] input = "00019{\"msg_name\":\"pong\"}".getBytes(StandardCharsets.UTF_8);
        FramedConnection connection = new FramedConnection(new ByteArrayInputStream(input), new ByteArrayOutputStream());

        assertEquals("{\"msg_name\":\"pong\"}", connection.read());
    }

    private static void testHeartbeatAction() {
        String json = Messages.heartbeatAction("match-1", 7, 1004);
        assertEquals("{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"match-1\","
                + "\"round\":7,\"playerId\":1004,\"actions\":[]}}", json);
    }

    private static void assertEquals(String expected, String actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError("expected <" + expected + "> but got <" + actual + ">");
        }
    }
}
