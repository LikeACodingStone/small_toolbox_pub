package com.qmedia.classifier;

import android.net.Uri;
import org.json.JSONObject;

final class Track {
    final String uri, parent, name;
    Track(String uri, String parent, String name) {
        this.uri = uri; this.parent = parent; this.name = name;
    }
    Uri uri() { return Uri.parse(uri); }
    JSONObject json() throws Exception {
        return new JSONObject().put("uri", uri).put("parent", parent).put("name", name);
    }
    static Track from(JSONObject o) throws Exception {
        return new Track(o.getString("uri"), o.getString("parent"), o.getString("name"));
    }
}
