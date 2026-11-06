package com.qmedia.classifier;

import android.net.Uri;
import org.json.JSONObject;
import java.util.Locale;

final class Track {
    final String uri, parent, name;
    Track(String uri, String parent, String name) {
        this.uri = uri; this.parent = parent; this.name = name;
    }
    /** Singer = filename text before " - " (case-insensitive); empty when the name has no such prefix. */
    String singer() {
        int i = name.indexOf(" - ");
        return i > 0 ? name.substring(0, i).trim().toLowerCase(Locale.ROOT) : "";
    }
    Uri uri() { return Uri.parse(uri); }
    JSONObject json() throws Exception {
        return new JSONObject().put("uri", uri).put("parent", parent).put("name", name);
    }
    static Track from(JSONObject o) throws Exception {
        return new Track(o.getString("uri"), o.getString("parent"), o.getString("name"));
    }
}
