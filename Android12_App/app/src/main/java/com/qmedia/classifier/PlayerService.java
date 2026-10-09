package com.qmedia.classifier;

import android.app.*;
import android.content.*;
import android.media.*;
import android.media.session.*;
import android.net.Uri;
import android.os.*;
import org.json.*;
import java.io.File;
import java.util.*;
import java.util.concurrent.*;

public final class PlayerService extends Service {
    public static final String[] GENRES={"other","rockPOP","blues","country","chinese","punk","hardrock","jPop","solo","metal"};
    private static final String CHANNEL="playback";
    private final ScheduledExecutorService worker=Executors.newSingleThreadScheduledExecutor();
    private final Handler main=new Handler(Looper.getMainLooper());
    public interface Listener { void changed(State state); }
    private volatile Listener listener;
    public static final class State {
        public String title="No track selected",folder="Select a music folder",log="Use OPEN to choose a folder",mode="SEQ";
        public boolean playing,busy,classified; public int position,duration,index,total,volume=50,retained;
    }
    private volatile boolean playbackRequested;
    private volatile State snapshot=new State();
    public final class LocalBinder extends Binder { public PlayerService service(){return PlayerService.this;} }
    private final LocalBinder binder=new LocalBinder();
    private Store store; private Documents docs; private MediaPlayer player;
    private MediaSession session; private AudioManager audio; private AudioFocusRequest focus;
    private File cache; private Track current;
    private String root="",destination="",mode="SEQ",log="Use OPEN to choose a folder";
    private int volume=50; private boolean classified,busy,resumeOnFocus;
    private final List<Track> tracks=new ArrayList<>();
    private final List<String> queue=new ArrayList<>(),back=new ArrayList<>(),successors=new ArrayList<>();
    private final List<History> history=new ArrayList<>();
    private final Set<String> failed=new HashSet<>();
    private final Random random=new Random(System.currentTimeMillis());
    private static final class History { final Track track; String status="available"; History(Track t){track=t;} }
    private final BroadcastReceiver noisy=new BroadcastReceiver(){@Override public void onReceive(Context c,Intent i){pauseForEntry();}};
    private final AudioDeviceCallback audioDevices=new AudioDeviceCallback(){
        @Override public void onAudioDevicesRemoved(AudioDeviceInfo[] removed){
            for(AudioDeviceInfo device:removed){
                if(!device.isSink())continue;
                int type=device.getType();
                if(type==AudioDeviceInfo.TYPE_WIRED_HEADSET||type==AudioDeviceInfo.TYPE_WIRED_HEADPHONES
                    ||type==AudioDeviceInfo.TYPE_USB_HEADSET||type==AudioDeviceInfo.TYPE_BLUETOOTH_A2DP
                    ||type==AudioDeviceInfo.TYPE_BLUETOOTH_SCO||type==AudioDeviceInfo.TYPE_BLE_HEADSET){
                    pauseForEntry();return;
                }
            }
        }
    };
    interface Task { void execute() throws Exception; }
    @Override public void onCreate() {
        super.onCreate();
        File[] stale=getCacheDir().listFiles((dir,name)->name.startsWith("playing-"));
        if(stale!=null)for(File file:stale)file.delete();
        store=new Store(this); docs=new Documents(getContentResolver());
        mode=store.get("mode","SEQ");volume=Integer.parseInt(store.get("volume","50"));
        audio=(AudioManager)getSystemService(AUDIO_SERVICE);
        audio.registerAudioDeviceCallback(audioDevices,main);
        focus=new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
            .setOnAudioFocusChangeListener(change->run(()->{
                if(change==AudioManager.AUDIOFOCUS_GAIN){if(player!=null)player.setVolume(volume/100f,volume/100f);if(resumeOnFocus){resumeOnFocus=false;resume();}}
                else if(change==AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK){if(player!=null)player.setVolume(volume/500f,volume/500f);}
                else pause(change==AudioManager.AUDIOFOCUS_LOSS_TRANSIENT);
            }),main).build();
        registerReceiver(noisy,new IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY));
        NotificationManager nm=getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL,"Music playback",NotificationManager.IMPORTANCE_LOW));
        session=new MediaSession(this,"RingPlayer");
        session.setCallback(new MediaSession.Callback(){
            @Override public void onPlay(){run(()->resume());}
            @Override public void onPause(){run(()->pause(false));}
            @Override public void onSkipToNext(){next();}
            @Override public void onSkipToPrevious(){previous();}
        });
        session.setActive(true);
        startForeground(1,notification(false));
        worker.scheduleWithFixedDelay(()->{try{publish(false);}catch(Exception ignored){}},0,500,TimeUnit.MILLISECONDS);
        run(()->{
            String saved=store.get("root","");
            if(!saved.isEmpty()) openInternal(saved,"");
        });
    }
    @Override public IBinder onBind(Intent intent){return binder;}
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent!=null){String action=intent.getAction();if("toggle".equals(action))toggle();else if("next".equals(action))next();else if("previous".equals(action))previous();}
        return START_NOT_STICKY;
    }
    public void listen(Listener value){listener=value;if(value!=null)value.changed(snapshot);}
    private void run(Task task){worker.execute(()->{try{task.execute();}catch(Exception e){log="Error: "+(e.getMessage()==null?e.getClass().getSimpleName():e.getMessage());}finally{busy=false;publish(true);}});}
    private Track find(String uri){for(Track t:tracks)if(t.uri.equals(uri))return t;return null;}
    public void open(String source){run(()->openInternal(source,""));}
    private void openInternal(String source,String target)throws Exception{
        playbackRequested=false;
        pause(false);
        busy=true;log="Scanning folder...";publish(true);
        Uri sourceFolder=docs.root(Uri.parse(source));
        List<Track> scanned=docs.scan(sourceFolder);
        String destinationError=null;
        if(target.isEmpty()){
            try{target=docs.siblingClassification(this,Uri.parse(source)).toString();}
            catch(Exception e){destinationError=e.getMessage();}
        }
        release();root=source;destination=target;tracks.clear();tracks.addAll(scanned);history.clear();back.clear();failed.clear();current=null;classified=false;
        store.set("root",root);store.set("destination:"+root,destination);
        queue.clear();String saved=store.get("queue:"+root,"");
        if(saved.isEmpty()){for(Track t:tracks)queue.add(t.uri);Collections.shuffle(queue,random);}
        else {JSONArray a=new JSONArray(saved);for(int i=0;i<a.length();i++)if(find(a.getString(i))!=null)queue.add(a.getString(i));}
        Track remembered=find(store.get("current:"+root,""));
        play(remembered!=null?remembered:chooseNext(),true);
        log="Loaded "+tracks.size()+" tracks";
        if(destinationError!=null)log+=". Cannot prepare classify folder: "+destinationError;
    }
    private void saveQueue(){store.set("queue:"+root,new JSONArray(queue).toString());}
    private Track chooseNext(){
        if(tracks.isEmpty())return null;
        if(mode.equals("RANDOM")){
            queue.removeIf(u->find(u)==null||failed.contains(u));
            if(queue.isEmpty()){
                for(Track t:tracks)if(!failed.contains(t.uri))queue.add(t.uri);
                Collections.shuffle(queue,random);
                if(queue.size()>1&&current!=null&&queue.get(0).equals(current.uri))Collections.swap(queue,0,1);
            }
            if(queue.isEmpty())return null;
            String chosen=queue.remove(0);saveQueue();return find(chosen);
        }
        if(classified)for(String u:successors){Track t=find(u);if(t!=null&&!failed.contains(u))return t;}
        int at=-1;if(current!=null)for(int i=0;i<tracks.size();i++)if(tracks.get(i).uri.equals(current.uri))at=i;
        for(int i=1;i<=tracks.size();i++){Track t=tracks.get((at+i)%tracks.size());if(!failed.contains(t.uri))return t;}
        return null;
    }
    private void release(){if(player!=null){player.release();player=null;}if(cache!=null){cache.delete();cache=null;}}
    private void play(Track track,boolean navigation)throws Exception{
        if(navigation&&current!=null&&track!=null&&!current.uri.equals(track.uri))back.add(current.uri);
        release();current=track;classified=false;successors.clear();
        if(track==null){log=tracks.isEmpty()?"No tracks available":"No playable tracks";audio.abandonAudioFocusRequest(focus);return;}
        busy=true;log="Loading track...";publish(true);
        try {
            cache=File.createTempFile("playing-",".audio",getCacheDir());docs.cache(track,cache);
            player=new MediaPlayer();
            player.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());
            player.setWakeMode(this,PowerManager.PARTIAL_WAKE_LOCK);
            player.setDataSource(cache.getAbsolutePath());player.prepare();player.setVolume(volume/100f,volume/100f);
            final MediaPlayer loaded=player;
            player.setOnCompletionListener(p->run(()->{if(player==loaded)play(chooseNext(),true);}));
            player.setOnErrorListener((p,what,extra)->{run(()->{if(player==loaded){failed.add(track.uri);play(chooseNext(),true);log="Cannot decode track; skipped";}});return true;});
            if(history.isEmpty()||!history.get(history.size()-1).track.uri.equals(track.uri))history.add(new History(track));
            queue.remove(track.uri);saveQueue();store.set("current:"+root,track.uri);
            if(playbackRequested)resume();else log="Paused";
        }catch(Exception e){
            failed.add(track.uri);release();log="Cannot play: "+track.name;
            worker.execute(()->{try{play(chooseNext(),true);}catch(Exception ignored){}finally{busy=false;publish(true);}});
        }
    }
    private void resume(){playbackRequested=true;if(player!=null){if(audio.requestAudioFocus(focus)==AudioManager.AUDIOFOCUS_REQUEST_GRANTED){player.start();log="Playing";}else log="Audio focus unavailable";}}
    private void pause(boolean automatic){playbackRequested=false;resumeOnFocus=automatic&&player!=null&&player.isPlaying();if(player!=null&&player.isPlaying())player.pause();if(!automatic)audio.abandonAudioFocusRequest(focus);}
    public void pauseForEntry(){playbackRequested=false;run(()->pause(false));}
    public void toggle(){run(()->{if(player!=null){if(player.isPlaying())pause(false);else resume();}else {playbackRequested=true;play(chooseNext(),true);}});}
    public void next(){run(()->play(chooseNext(),true));}
    public void previous(){run(()->{
        Track target=null;
        if(mode.equals("RANDOM")){while(!back.isEmpty()&&target==null)target=find(back.remove(back.size()-1));}
        else if(!tracks.isEmpty()){int at=-1;for(int i=0;i<tracks.size();i++)if(current!=null&&tracks.get(i).uri.equals(current.uri))at=i;target=tracks.get(at<0?tracks.size()-1:Math.floorMod(at-1,tracks.size()));}
        if(target!=null)play(target,false);else log="No previous track";
    });}
    public void mode(String value){run(()->{mode=value;store.set("mode",mode);log=mode.equals("SEQ")?"Sequential mode":"Random mode";});}
    public void volume(int delta){run(()->{volume=Math.max(0,Math.min(100,volume+delta));store.set("volume",Integer.toString(volume));if(player!=null)player.setVolume(volume/100f,volume/100f);log="Volume "+volume+"%";});}
    private void forget(Track track,String status){tracks.removeIf(t->t.uri.equals(track.uri));queue.remove(track.uri);for(History h:history)if(h.track.uri.equals(track.uri))h.status=status;saveQueue();}
    public void classify(String genre){run(()->{
        if(!Arrays.asList(GENRES).contains(genre))return;
        if(current==null||find(current.uri)==null){log=classified?"Track already classified":"Current track unavailable";return;}
        if(destination.isEmpty()){
            destination=docs.siblingClassification(this,Uri.parse(root)).toString();
            store.set("destination:"+root,destination);
        }
        busy=true;publish(true);
        int index=tracks.indexOf(current);List<String> order=new ArrayList<>();for(int i=1;i<tracks.size();i++)order.add(tracks.get((index+i)%tracks.size()).uri);
        Uri target=docs.directory(docs.root(Uri.parse(destination)),genre);
        docs.move(current,target);forget(current,"classified");successors.clear();successors.addAll(order);classified=true;
        log="Moved: "+genre+" · Still "+(player!=null&&player.isPlaying()?"playing":"paused");
    });}
    private void deleteTrack(Track track)throws Exception{
        // Prune before moving: a cleanup failure never leaves an unrecorded new deletion.
        List<Store.Deleted> retained=store.trash(root);
        for(int i=9;i<retained.size();i++){Store.Deleted old=retained.get(i);docs.delete(old.stored.uri());store.removeTrash(old.id);}
        Uri trash=docs.directory(docs.root(Uri.parse(root)),"tmp_trash");
        Uri moved=docs.move(track,trash);
        Track stored=new Track(moved.toString(),trash.toString(),docs.name(moved));
        try{store.addTrash(root,track,stored);}catch(Exception e){docs.move(stored,Uri.parse(track.parent));throw e;}
        forget(track,"deleted");
    }
    public void deleteCurrent(){run(()->{
        if(current==null||find(current.uri)==null){log=classified?"Already classified; cannot delete":"Current track unavailable";return;}
        Track old=current;int at=tracks.indexOf(old);deleteTrack(old);
        Track next=mode.equals("RANDOM")?chooseNext():(tracks.isEmpty()?null:tracks.get(at%tracks.size()));
        play(next,true);log="Deleted";
    });}
    public void deletePrevious(){run(()->{
        if(current==null||history.size()<2){log="Previous track unavailable";return;}
        History h=history.get(history.size()-2);
        if(h.status.equals("classified")){log="Already classified; cannot delete";return;}
        if(!h.status.equals("available")||find(h.track.uri)==null||(current!=null&&h.track.uri.equals(current.uri))){log="Previous track unavailable";return;}
        deleteTrack(h.track);log="Previous track deleted";
    });}
    public void restore(){run(()->{
        List<Store.Deleted> list=store.trash(root);if(list.isEmpty()){log="Nothing to restore";return;}
        Store.Deleted item=list.get(0);
        Track restoreSource=new Track(item.stored.uri,item.stored.parent,item.original.name);
        Uri result=docs.move(restoreSource,Uri.parse(item.original.parent));store.removeTrash(item.id);
        Track restored=new Track(result.toString(),item.original.parent,docs.name(result));
        tracks.add(restored);tracks.sort(Comparator.comparing(t->t.name.toLowerCase(Locale.ROOT)));queue.add(restored.uri);saveQueue();log="Restored";
    });}
    private Notification notification(boolean playing){
        Intent launch=new Intent(this,MainActivity.class);
        PendingIntent open=PendingIntent.getActivity(this,0,launch,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b=new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(current==null?"RingPlayer":current.name).setContentText(log).setContentIntent(open).setOnlyAlertOnce(true).setOngoing(playing)
            .setStyle(new Notification.MediaStyle().setMediaSession(session.getSessionToken()).setShowActionsInCompactView(0,1,2));
        String[] actions={"previous","toggle","next"};String[] labels={"Previous",playing?"Pause":"Play","Next"};
        int[] icons={android.R.drawable.ic_media_previous,playing?android.R.drawable.ic_media_pause:android.R.drawable.ic_media_play,android.R.drawable.ic_media_next};
        for(int i=0;i<3;i++)b.addAction(new Notification.Action.Builder(icons[i],labels[i],PendingIntent.getService(this,i,new Intent(this,PlayerService.class).setAction(actions[i]),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT)).build());
        return b.build();
    }
    private void publish(boolean notification){
        State s=new State();s.title=current==null?"No track selected":current.name;s.mode=mode;s.log=log;s.volume=volume;s.total=tracks.size();s.busy=busy;s.classified=classified;
        s.folder=root.isEmpty()?"Select a music folder":Uri.decode(DocumentsContractCompat.id(root));
        if(current!=null)for(int i=0;i<tracks.size();i++)if(tracks.get(i).uri.equals(current.uri))s.index=i+1;
        if(player!=null){try{s.playing=player.isPlaying();s.position=player.getCurrentPosition();s.duration=player.getDuration();}catch(IllegalStateException ignored){}}
        try{s.retained=store.trash(root).size();}catch(Exception ignored){}
        snapshot=s;
        session.setPlaybackState(new PlaybackState.Builder().setActions(PlaybackState.ACTION_PLAY|PlaybackState.ACTION_PAUSE|PlaybackState.ACTION_SKIP_TO_NEXT|PlaybackState.ACTION_SKIP_TO_PREVIOUS)
            .setState(s.playing?PlaybackState.STATE_PLAYING:PlaybackState.STATE_PAUSED,s.position,s.playing?1f:0f).build());
        if(notification){session.setMetadata(new MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_TITLE,s.title).putLong(MediaMetadata.METADATA_KEY_DURATION,s.duration).build());getSystemService(NotificationManager.class).notify(1,notification(s.playing));}
        main.post(()->{Listener l=listener;if(l!=null)l.changed(s);});
    }
    private static final class DocumentsContractCompat {static String id(String uri){try{return android.provider.DocumentsContract.getTreeDocumentId(Uri.parse(uri));}catch(Exception e){return uri;}}}
    @Override public void onDestroy(){listener=null;unregisterReceiver(noisy);audio.unregisterAudioDeviceCallback(audioDevices);worker.execute(()->{release();audio.abandonAudioFocusRequest(focus);session.release();store.close();});worker.shutdown();super.onDestroy();}
}
