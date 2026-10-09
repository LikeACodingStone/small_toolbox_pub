package com.qmedia.classifier;

import android.content.ContentResolver;
import android.content.Context;
import android.os.Environment;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import java.io.*;
import java.util.*;

final class Documents {
    private final ContentResolver resolver;
    private static final Set<String> AUDIO = new HashSet<>(Arrays.asList("mp3","wav","ogg","opus","flac","m4a","aac","wma"));
    Documents(ContentResolver resolver) { this.resolver = resolver; }
    Uri root(Uri tree) {
        if ("file".equals(tree.getScheme())) return tree;
        // A child document URI already identifies the destination within its grant.
        if (tree.getPathSegments().contains("document")) return tree;
        return DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree));
    }
    Uri siblingClassification(Context context, Uri source) throws IOException {
        if (!Environment.isExternalStorageManager())
            throw new IOException("Enable OPEN → All files access to create classify beside the music folder.");
        if (!"com.android.externalstorage.documents".equals(source.getAuthority()))
            throw new IOException("Choose a local or SD card music folder to create a sibling classify folder.");
        String id = DocumentsContract.getDocumentId(root(source));
        int colon = id.indexOf(':');
        if (colon < 0) throw new IOException("Cannot locate the selected storage volume");
        String volumeId = id.substring(0, colon);
        for (StorageVolume volume : context.getSystemService(StorageManager.class).getStorageVolumes()) {
            if (!(volume.isPrimary() && "primary".equals(volumeId)) &&
                    !volumeId.equalsIgnoreCase(volume.getUuid())) continue;
            File base = volume.getDirectory();
            if (base == null) continue;
            base = base.getCanonicalFile();
            File selected = new File(base, id.substring(colon + 1)).getCanonicalFile();
            if (selected.equals(base) || !selected.toPath().startsWith(base.toPath()))
                throw new IOException("Choose a music subfolder, not the storage root");
            File destination = new File(selected.getParentFile(), "classify");
            if (destination.getCanonicalFile().equals(selected))
                throw new IOException("Choose an unclassified music folder, not classify itself");
            return directory(Uri.fromFile(selected.getParentFile()), "classify");
        }
        throw new IOException("Storage is unavailable. Reconnect the SD card and use OPEN again.");
    }
    String name(Uri uri) throws IOException {
        if ("file".equals(uri.getScheme())) return new File(uri.getPath()).getName();
        try (Cursor c = resolver.query(uri, new String[]{DocumentsContract.Document.COLUMN_DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst()) return c.getString(0);
        }
        throw new IOException("Folder is unavailable. Use OPEN to grant access again.");
    }
    List<Track> scan(Uri folder) throws IOException {
        List<Track> tracks = new ArrayList<>();
        walk(folder, tracks, new HashSet<>());
        tracks.sort(Comparator.comparing(t -> t.name.toLowerCase(Locale.ROOT)));
        return tracks;
    }
    private void walk(Uri folder, List<Track> tracks, Set<String> visited) throws IOException {
        if (!visited.add(DocumentsContract.getDocumentId(folder))) return;
        for (Entry e : children(folder)) {
            if (e.name.startsWith(".")) continue;
            if (e.directory) {
                if (!e.name.equalsIgnoreCase("tmp_trash") && !e.name.equalsIgnoreCase("classify")) walk(e.uri, tracks, visited);
            } else {
                int dot = e.name.lastIndexOf('.');
                if (dot >= 0 && AUDIO.contains(e.name.substring(dot+1).toLowerCase(Locale.ROOT)))
                    tracks.add(new Track(e.uri.toString(), folder.toString(), e.name));
            }
        }
    }
    static final class Entry {
        final Uri uri; final String name; final boolean directory;
        Entry(Uri uri, String name, boolean directory) { this.uri=uri; this.name=name; this.directory=directory; }
    }
    List<Entry> children(Uri folder) throws IOException {
        List<Entry> entries = new ArrayList<>();
        if ("file".equals(folder.getScheme())) {
            File[] files = new File(folder.getPath()).listFiles();
            if (files == null) throw new IOException("Cannot read classification folder. Check All files access and SD card.");
            for (File file : files) entries.add(new Entry(Uri.fromFile(file), file.getName(), file.isDirectory()));
            return entries;
        }
        Uri query = DocumentsContract.buildChildDocumentsUriUsingTree(folder, DocumentsContract.getDocumentId(folder));
        try (Cursor c = resolver.query(query, new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME, DocumentsContract.Document.COLUMN_MIME_TYPE}, null, null, null)) {
            if (c == null) throw new IOException("Cannot read folder");
            while (c.moveToNext()) entries.add(new Entry(DocumentsContract.buildDocumentUriUsingTree(folder,c.getString(0)),
                    c.getString(1), DocumentsContract.Document.MIME_TYPE_DIR.equals(c.getString(2))));
        }
        return entries;
    }
    Uri directory(Uri parent, String name) throws IOException {
        if ("file".equals(parent.getScheme())) {
            File folder = new File(parent.getPath(), name);
            if (!folder.isDirectory() && !folder.mkdir()) throw new IOException("Cannot create folder: " + folder);
            return Uri.fromFile(folder);
        }
        for (Entry e : children(parent)) if (e.name.equals(name)) {
            if (!e.directory) throw new IOException("A file blocks folder: " + name);
            return e.uri;
        }
        Uri uri = DocumentsContract.createDocument(resolver,parent,DocumentsContract.Document.MIME_TYPE_DIR,name);
        if (uri == null) throw new IOException("Cannot create folder: " + name);
        return uri;
    }
    Uri move(Track source, Uri target) throws IOException {
        Set<String> existing = new HashSet<>();
        for (Entry e : children(target)) existing.add(e.name);
        String name = source.name;
        int dot = name.lastIndexOf('.');
        String stem = dot > 0 ? name.substring(0,dot) : name;
        String suffix = dot > 0 ? name.substring(dot) : "";
        int n = 1;
        while (existing.contains(name)) name = stem + " (" + n++ + ")" + suffix;
        // Prefer provider-native move for fast local operations without copying.
        if (!"file".equals(target.getScheme()) && name.equals(name(source.uri())) && Objects.equals(source.uri().getAuthority(), target.getAuthority())) {
            try {
                Uri moved = DocumentsContract.moveDocument(resolver,source.uri(),Uri.parse(source.parent),target);
                if (moved != null) return moved;
            } catch (UnsupportedOperationException | IllegalArgumentException ignored) {
                // Providers without move support use the checked copy/delete fallback.
            }
        }
        String mime = resolver.getType(source.uri());
        Uri created;
        if ("file".equals(target.getScheme())) {
            File file = new File(target.getPath(), name);
            if (!file.createNewFile()) throw new IOException("Destination already exists: " + name);
            created = Uri.fromFile(file);
        } else created = DocumentsContract.createDocument(resolver,target,mime == null ? "application/octet-stream" : mime,name);
        if (created == null) throw new IOException("Cannot create destination file");
        try {
            try (InputStream in = resolver.openInputStream(source.uri()); OutputStream out = "file".equals(created.getScheme()) ? new FileOutputStream(new File(created.getPath())) : resolver.openOutputStream(created,"w")) {
                if (in == null || out == null) throw new IOException("Cannot open file streams");
                copy(in,out);
            }
            if (!DocumentsContract.deleteDocument(resolver,source.uri())) throw new IOException("Cannot remove source file");
        } catch (Exception error) {
            try { delete(created); } catch (Exception ignored) { }
            throw new IOException("Move failed: " + error.getMessage(),error);
        }
        return created;
    }
    void delete(Uri uri) throws IOException {
        if ("file".equals(uri.getScheme())) {
            if (!new File(uri.getPath()).delete()) throw new IOException("Cannot delete file");
            return;
        }
        if (!DocumentsContract.deleteDocument(resolver,uri)) throw new IOException("Cannot delete retained file");
    }
    void cache(Track source, File file) throws IOException {
        try (InputStream in = resolver.openInputStream(source.uri()); OutputStream out = new FileOutputStream(file)) {
            if (in == null) throw new IOException("Track unavailable");
            copy(in,out);
        }
    }
    static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buffer = new byte[65536]; int length;
        while ((length=in.read(buffer)) != -1) out.write(buffer,0,length);
    }
}
