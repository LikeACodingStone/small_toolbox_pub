package com.qmedia.classifier;

import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.text.TextUtils;
import android.view.*;
import android.widget.*;
import java.util.*;

public final class MainActivity extends Activity {
    private static final int SOURCE=10;
    private static final int BG=0xffF2F6FA,INK=0xff182D42,MUTED=0xff62758A,BLUE=0xff007FAD,RED=0xffC63D47;
    private PlayerService service; private boolean bound,compact; private String pendingSource;
    private TextView title,folder,count,elapsed,duration,volume,log;
    private Button play,seq,random,restore,show,hide;
    private String renderedMode="";
    private boolean awaitingAllFilesAccess;
    private LinearLayout genres;
    private final List<Button> actions=new ArrayList<>();
    private final ServiceConnection connection=new ServiceConnection(){
        @Override public void onServiceConnected(ComponentName n,IBinder binder){service=((PlayerService.LocalBinder)binder).service();service.listen(MainActivity.this::render);submitFolders();}
        @Override public void onServiceDisconnected(ComponentName n){service=null;}
    };
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);
        compact=getPreferences(0).getBoolean("compact",false);
        if(saved!=null){pendingSource=saved.getString("pendingSource");awaitingAllFilesAccess=saved.getBoolean("awaitingAllFilesAccess");}
        buildUi();
        startForegroundService(new Intent(this,PlayerService.class));
    }
    @Override protected void onStart(){super.onStart();bound=bindService(new Intent(this,PlayerService.class),connection,BIND_AUTO_CREATE);}
    @Override protected void onStop(){if(service!=null)service.listen(null);if(bound){unbindService(connection);bound=false;}service=null;super.onStop();}
    @Override protected void onSaveInstanceState(Bundle out){super.onSaveInstanceState(out);out.putString("pendingSource",pendingSource);out.putBoolean("awaitingAllFilesAccess",awaitingAllFilesAccess);}
    @Override protected void onResume(){
        super.onResume();
        if(awaitingAllFilesAccess){
            awaitingAllFilesAccess=false;
            new AlertDialog.Builder(this).setTitle("All files access")
                .setMessage(Environment.isExternalStorageManager()
                    ? "All files access is enabled. Choose your music folder next."
                    : "All files access is not enabled. You can still choose folders and allow access individually.")
                .setPositiveButton("Choose folder",(d,w)->beginOpen()).setNegativeButton("Close",null).show();
        }
    }
    private int dp(int value){return (int)(value*getResources().getDisplayMetrics().density+.5f);}
    private GradientDrawable background(int color){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(14));return d;}
    private LinearLayout column(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);return l;}
    private TextView text(String value,int size,int color,boolean bold){TextView v=new TextView(this);v.setText(value);v.setTextSize(size);v.setTextColor(color);if(bold)v.setTypeface(null,Typeface.BOLD);return v;}
    private void space(LinearLayout l,int size){View v=new View(this);l.addView(v,new LinearLayout.LayoutParams(1,dp(size)));}
    private void add(LinearLayout l,View v){l.addView(v,new LinearLayout.LayoutParams(-1,-2));}
    private LinearLayout row(LinearLayout parent){LinearLayout l=new LinearLayout(this);l.setGravity(Gravity.CENTER_VERTICAL);add(parent,l);return l;}
    private Button button(LinearLayout row,String label,int color,Runnable callback){
        Button b=new Button(this);b.setText(label);b.setTextSize(12);b.setAllCaps(false);b.setTextColor(color==BLUE||color==RED?Color.WHITE:INK);b.setBackground(background(color));b.setMinWidth(0);b.setMinimumWidth(0);b.setPadding(dp(3),0,dp(3),0);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,dp(50),1);p.setMargins(dp(3),dp(3),dp(3),dp(3));row.addView(b,p);
        b.setOnClickListener(v->callback.run());actions.add(b);return b;
    }
    private void withService(java.util.function.Consumer<PlayerService> action){if(service!=null)action.accept(service);}
    private LinearLayout card(LinearLayout parent){LinearLayout c=column();c.setPadding(dp(16),dp(14),dp(16),dp(14));c.setBackground(background(Color.WHITE));add(parent,c);return c;}
    private void fullText(TextView v){v.setOnLongClickListener(view->{new AlertDialog.Builder(this).setMessage(v.getTag()==null?v.getText():v.getTag().toString()).setPositiveButton("Close",null).show();return true;});}
    private void buildUi(){
        LinearLayout outer=column();outer.setBackgroundColor(BG);outer.setPadding(dp(12),dp(8),dp(12),dp(8));setContentView(outer);
        LinearLayout header=row(outer);TextView brand=text("RingPlayer",23,INK,true);header.addView(brand,new LinearLayout.LayoutParams(0,dp(52),3));brand.setGravity(Gravity.CENTER_VERTICAL);
        button(header,"OPEN",BLUE,this::beginOpen);
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(false);outer.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        LinearLayout body=column();scroll.addView(body);space(body,8);
        LinearLayout source=card(body);add(source,text("SOURCE FOLDER",10,MUTED,true));folder=text("Select a music folder",14,INK,true);folder.setSingleLine();folder.setEllipsize(TextUtils.TruncateAt.START);fullText(folder);add(source,folder);
        space(body,12);LinearLayout now=card(body);
        LinearLayout cap=row(now);TextView label=text("NOW PLAYING",10,BLUE,true);cap.addView(label,new LinearLayout.LayoutParams(0,-2,1));count=text("0 / 0",12,MUTED,false);cap.addView(count);
        space(now,10);title=text("No track selected",22,INK,true);title.setSingleLine();title.setEllipsize(TextUtils.TruncateAt.END);fullText(title);add(now,title);
        space(now,18);LinearLayout times=row(now);elapsed=text("00:00",14,INK,true);times.addView(elapsed,new LinearLayout.LayoutParams(0,-2,1));duration=text("00:00",14,MUTED,false);times.addView(duration);
        space(now,12);LinearLayout transport=row(now);button(transport,"PREV",BG,()->withService(PlayerService::previous));play=button(transport,"PLAY",BLUE,()->withService(PlayerService::toggle));button(transport,"NEXT",BG,()->withService(PlayerService::next));
        space(body,10);LinearLayout volumes=row(body);button(volumes,"VOL−",Color.WHITE,()->withService(s->s.volume(-10)));volume=text("50%",13,MUTED,true);volume.setGravity(Gravity.CENTER);volumes.addView(volume,new LinearLayout.LayoutParams(0,dp(48),1));button(volumes,"VOL+",Color.WHITE,()->withService(s->s.volume(10)));
        space(body,6);LinearLayout modes=row(body);show=button(modes,"SHOW",Color.WHITE,()->setCompact(false));hide=button(modes,"HIDE",Color.WHITE,()->setCompact(true));seq=button(modes,"SEQ",RED,()->withService(s->s.mode("SEQ")));random=button(modes,"RANDOM",Color.WHITE,()->withService(s->s.mode("RANDOM")));
        space(body,12);genres=column();add(body,genres);add(genres,text("MOVE TO GENRE · Playback continues",11,MUTED,true));space(genres,8);
        for(int i=0;i<PlayerService.GENRES.length;i+=2){LinearLayout r=row(genres);for(int j=i;j<i+2;j++){String genre=PlayerService.GENRES[j];Button genreButton=button(r,genre,0xffDFEDF8,()->withService(s->s.classify(genre)));genreButton.setTextSize(android.util.TypedValue.COMPLEX_UNIT_PX,play.getTextSize());genreButton.setTypeface(play.getTypeface());}}
        space(body,10);
        log=text("Use OPEN to choose a folder",12,0xff276648,false);log.setPadding(dp(12),dp(10),dp(12),dp(10));log.setBackground(background(0xffE2F2E9));log.setMaxLines(2);log.setEllipsize(TextUtils.TruncateAt.END);fullText(log);add(outer,log);space(outer,6);
        LinearLayout deletes=row(outer);button(deletes,"DEL",0xffFCE8E9,()->withService(PlayerService::deleteCurrent));button(deletes,"DEL PRE",0xffFCE8E9,()->withService(PlayerService::deletePrevious));restore=button(deletes,"RESTORE",BLUE,()->withService(PlayerService::restore));
        setCompact(compact);
    }
    private void setCompact(boolean value){compact=value;genres.setVisibility(value?View.GONE:View.VISIBLE);show.setBackground(background(value?BLUE:Color.WHITE));show.setTextColor(value?Color.WHITE:INK);hide.setBackground(background(value?Color.WHITE:BLUE));hide.setTextColor(value?INK:Color.WHITE);getPreferences(0).edit().putBoolean("compact",value).apply();}
    private void fitTitle(String value){
        if(value.equals(title.getTag()))return;
        title.setText(value);
        title.setTag(value);title.post(()->{
            int available=title.getWidth()-title.getPaddingLeft()-title.getPaddingRight();if(available<=0)return;
            title.setTextSize(22);title.setLetterSpacing(0);
            for(float spacing=0;spacing>=-.06f&&title.getPaint().measureText(value)>available;spacing-=.02f)title.setLetterSpacing(spacing);
            for(int size=21;size>=12&&title.getPaint().measureText(value)>available;size--)title.setTextSize(size);
        });
    }
    private static String time(int ms){int seconds=ms/1000;return String.format(Locale.US,"%02d:%02d",seconds/60,seconds%60);}
    private void updateText(TextView view,String value){if(!value.contentEquals(view.getText()))view.setText(value);}
    private void render(PlayerService.State s){
        fitTitle(s.title);updateText(folder,s.folder);folder.setTag(s.folder);updateText(count,String.format(Locale.US,"%d / %d",s.index,s.total));
        updateText(elapsed,time(s.position));updateText(duration,time(s.duration));updateText(volume,String.format(Locale.US,"%d%%",s.volume));updateText(play,s.playing?"PAUSE":"PLAY");updateText(log,s.log);log.setTag(s.log);
        if(!renderedMode.equals(s.mode)){renderedMode=s.mode;
        seq.setBackground(background(s.mode.equals("SEQ")?RED:Color.WHITE));seq.setTextColor(s.mode.equals("SEQ")?Color.WHITE:INK);
        random.setBackground(background(s.mode.equals("RANDOM")?RED:Color.WHITE));random.setTextColor(s.mode.equals("RANDOM")?Color.WHITE:INK);}
        updateText(restore,s.retained>0?"RESTORE ("+s.retained+")":"RESTORE");
        for(Button b:actions)if(b.isEnabled()==s.busy)b.setEnabled(!s.busy);
    }
    private void submitFolders(){if(service!=null&&pendingSource!=null){String source=pendingSource;pendingSource=null;service.open(source);}}
    private void beginOpen(){
        new AlertDialog.Builder(this).setTitle("Choose music folder")
            .setMessage("Choose the folder containing your music. The app automatically uses or creates a classify folder beside it, in its parent folder. Enable All files access to allow this. Classified tracks are excluded from the music scan. Your choice will be remembered.\n\nAll files access: "
                +(Environment.isExternalStorageManager()?"Enabled":"Not enabled")
                +". This optional permission can be managed in Settings. Android's protected-folder restrictions still apply.")
            .setNeutralButton("All files access",(d,w)->requestAllFilesAccess())
            .setPositiveButton("Choose folder",(d,w)->pick(SOURCE)).setNegativeButton("Cancel",null).show();
    }
    private void requestAllFilesAccess(){
        awaitingAllFilesAccess=true;
        try{
            startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                Uri.parse("package:"+getPackageName())));
        }catch(ActivityNotFoundException|SecurityException unavailable){
            try{
                startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
            }catch(ActivityNotFoundException|SecurityException unsupported){
                awaitingAllFilesAccess=false;
                new AlertDialog.Builder(this).setTitle("Open Settings manually")
                    .setMessage("Open Android Settings, search for All files access, and enable it for RingPlayer. If your device does not offer this setting, use OPEN to grant access to individual folders.")
                    .setPositiveButton("Close",null).show();
            }
        }
    }
    private void pick(int code){Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION|Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);startActivityForResult(i,code);}
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);if(request!=SOURCE||result!=RESULT_OK||data==null||data.getData()==null)return;
        Uri uri=data.getData();
        try{
            int flags=data.getFlags()&(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            if(flags!=(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_WRITE_URI_PERMISSION))throw new SecurityException("Folder must allow writing");
            getContentResolver().takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            pendingSource=uri.toString();
            submitFolders();
        }catch(Exception e){new AlertDialog.Builder(this).setTitle("Folder access failed").setMessage(e.getMessage()).setPositiveButton("Close",null).show();}
    }
}
