package com.qmedia.classifier;

import android.content.*;
import android.database.Cursor;
import android.database.sqlite.*;
import org.json.*;
import java.util.*;

final class Store extends SQLiteOpenHelper {
    Store(Context context) { super(context,"player.db",null,1); }
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE settings(k TEXT PRIMARY KEY,v TEXT NOT NULL)");
        db.execSQL("CREATE TABLE trash(id INTEGER PRIMARY KEY AUTOINCREMENT,root TEXT NOT NULL,original TEXT NOT NULL,stored TEXT NOT NULL)");
    }
    @Override public void onUpgrade(SQLiteDatabase db,int oldVersion,int newVersion) { }
    String get(String key,String fallback) {
        try(Cursor c=getReadableDatabase().rawQuery("SELECT v FROM settings WHERE k=?",new String[]{key})) {
            return c.moveToFirst()?c.getString(0):fallback;
        }
    }
    void set(String key,String value) {
        ContentValues v=new ContentValues();v.put("k",key);v.put("v",value);
        getWritableDatabase().insertWithOnConflict("settings",null,v,SQLiteDatabase.CONFLICT_REPLACE);
    }
    void addTrash(String root,Track original,Track stored) throws Exception {
        ContentValues v=new ContentValues();v.put("root",root);v.put("original",original.json().toString());v.put("stored",stored.json().toString());
        getWritableDatabase().insertOrThrow("trash",null,v);
    }
    static final class Deleted {
        final long id; final Track original,stored;
        Deleted(long id,Track original,Track stored) {this.id=id;this.original=original;this.stored=stored;}
    }
    List<Deleted> trash(String root) throws Exception {
        List<Deleted> out=new ArrayList<>();
        try(Cursor c=getReadableDatabase().rawQuery("SELECT id,original,stored FROM trash WHERE root=? ORDER BY id DESC",new String[]{root})) {
            while(c.moveToNext()) out.add(new Deleted(c.getLong(0),Track.from(new JSONObject(c.getString(1))),Track.from(new JSONObject(c.getString(2)))));
        }
        return out;
    }
    void removeTrash(long id) { getWritableDatabase().delete("trash","id=?",new String[]{Long.toString(id)}); }
}
