/* PulseAudio simple ABI, loaded at runtime (also supported by PipeWire).
 * No audio development package is needed. Emulation never blocks on audio IO.
 */
#include <dlfcn.h>
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>
typedef struct pa_simple pa_simple;
typedef struct { int format; uint32_t rate; uint8_t channels; } SampleSpec;
typedef struct { uint32_t maxlength, tlength, prebuf, minreq, fragsize; } BufferAttr;
static pthread_t audio_thread;
static pthread_mutex_t audio_mutex=PTHREAD_MUTEX_INITIALIZER;
static float audio_ring[8192];
static unsigned audio_read, audio_write;
static int audio_started;
static atomic_int audio_stop, audio_status, audio_muted;
static void audio_clear(void) {
    pthread_mutex_lock(&audio_mutex); audio_read=audio_write=0; pthread_mutex_unlock(&audio_mutex);
}
static void audio_push(const float *data, unsigned count) {
    if (!audio_started || atomic_load(&audio_status)!=1) return;
    pthread_mutex_lock(&audio_mutex);
    for (unsigned i=0; i<count; i++) {
        unsigned next=(audio_write+1)%8192;
        if (next==audio_read) break;
        audio_ring[audio_write]=data[i]; audio_write=next;
    }
    pthread_mutex_unlock(&audio_mutex);
}
static void *audio_run(void *unused) {
    (void)unused;
    void *lib=dlopen("libpulse-simple.so.0",RTLD_NOW|RTLD_LOCAL);
    if (!lib) { atomic_store(&audio_status,-1); return NULL; }
    pa_simple *(*create)(const char*,const char*,int,const char*,const char*,const SampleSpec*,const void*,const BufferAttr*,int*);
    int (*write_samples)(pa_simple*,const void*,size_t,int*);
    void (*destroy)(pa_simple*);
    *(void**)(&create)=dlsym(lib,"pa_simple_new");
    *(void**)(&write_samples)=dlsym(lib,"pa_simple_write");
    *(void**)(&destroy)=dlsym(lib,"pa_simple_free");
    if (!create || !write_samples || !destroy) { atomic_store(&audio_status,-1); dlclose(lib); return NULL; }
    SampleSpec spec={5,48000,1}; /* PA_SAMPLE_FLOAT32LE, mono */
    BufferAttr attr={16384,8192,0,2048,UINT32_MAX};
    int error=0;
    pa_simple *stream=create(NULL,"May NES",1,NULL,"NES audio",&spec,NULL,&attr,&error);
    if (!stream) { atomic_store(&audio_status,-1); dlclose(lib); return NULL; }
    atomic_store(&audio_status,1);
    while (!atomic_load(&audio_stop)) {
        float samples[512]={0};
        pthread_mutex_lock(&audio_mutex);
        for (unsigned i=0; i<512 && audio_read!=audio_write; i++) {
            samples[i]=audio_ring[audio_read]*0.65f; audio_read=(audio_read+1)%8192;
        }
        pthread_mutex_unlock(&audio_mutex);
        if (atomic_load(&audio_muted)) memset(samples,0,sizeof(samples));
        if (write_samples(stream,samples,sizeof(samples),&error)<0) { atomic_store(&audio_status,-1); break; }
    }
    destroy(stream); dlclose(lib); return NULL;
}
static void audio_start(void) {
    if (audio_started) return;
    atomic_store(&audio_stop,0); atomic_store(&audio_status,0);
    if (!pthread_create(&audio_thread,NULL,audio_run,NULL)) audio_started=1;
    else atomic_store(&audio_status,-1);
}
static void audio_close(void) {
    if (!audio_started) return;
    atomic_store(&audio_stop,1); pthread_join(audio_thread,NULL); audio_started=0; audio_clear();
}
