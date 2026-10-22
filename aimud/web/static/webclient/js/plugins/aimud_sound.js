/*
 * aimud's sounds in the web client. docs/sound.md 3.1, 3.4.
 *
 * The web client speaks what Mudlet speaks: on logging in it says it handles
 * Client.Media (GMCP's Core.Supports.Set, sent as the same inputfunc), and
 * from then on the server sends it client_media_play, _stop and _load, as it
 * would any GMCP client. So nothing on the server knows this is a browser,
 * except one thing: the web client pans a sound by itself, so it is sent the
 * pan rather than a copy of the sound made for one side.
 *
 * Web Audio, not <audio> elements: a loop has to loop without a gap, several
 * play at once, each fades and pans, and a sound the server preloads is
 * decoded once and played many times. A browser will not make a sound before
 * the page has been used, so the first key pressed wakes it.
 */
let aimud_sound_plugin = (function () {
    let context = null;
    let buffers = {};       // url -> Promise of an AudioBuffer
    let playing = {};       // key -> {source, gain, name, tag}
    let unkeyed = 0;

    var audio = function () {
        if (context === null) {
            let Made = window.AudioContext || window.webkitAudioContext;
            if (!Made) { return null; }
            context = new Made();
        }
        if (context.state === "suspended") { context.resume(); }
        return context;
    };

    var fetchSound = function (url) {
        if (!(url in buffers)) {
            buffers[url] = fetch(url)
                .then(function (answer) { return answer.arrayBuffer(); })
                .then(function (data) { return audio().decodeAudioData(data); })
                .catch(function (error) {
                    delete buffers[url];
                    console.log("aimud sound: could not fetch " + url, error);
                    return null;
                });
        }
        return buffers[url];
    };

    var address = function (kwargs) {
        return String(kwargs.url || "") + String(kwargs.name || "");
    };

    var fadeTo = function (gain, value, milliseconds) {
        let now = context.currentTime;
        gain.gain.cancelScheduledValues(now);
        gain.gain.setValueAtTime(gain.gain.value, now);
        gain.gain.linearRampToValueAtTime(value, now + milliseconds / 1000);
    };

    var stopOne = function (key, fadeout) {
        let found = playing[key];
        if (!found) { return; }
        delete playing[key];
        let wait = Math.max(0, Number(fadeout) || 0);
        if (wait > 0) {
            fadeTo(found.gain, 0, wait);
            found.source.stop(context.currentTime + wait / 1000 + 0.05);
        } else {
            found.source.stop();
        }
    };

    var play = function (args, kwargs) {
        kwargs = kwargs || {};
        if (!audio()) { return; }
        let key = kwargs.key ? String(kwargs.key) : "unkeyed-" + (unkeyed++);
        let name = String(kwargs.name || "");
        let already = playing[key];
        let volume = Math.max(0, Math.min(100, Number(kwargs.volume || 50))) / 100;
        if (already && already.name === name && kwargs["continue"] !== false) {
            fadeTo(already.gain, volume, 200);
            return;
        }
        if (already) { stopOne(key, kwargs.fadeout || 0); }
        fetchSound(address(kwargs)).then(function (buffer) {
            if (!buffer) { return; }
            let source = context.createBufferSource();
            source.buffer = buffer;
            let loops = Number(kwargs.loops || 1);
            source.loop = loops === -1 || loops > 1;
            let gain = context.createGain();
            let fadein = Number(kwargs.fadein || 0);
            gain.gain.value = fadein > 0 ? 0 : volume;
            let last = gain;
            source.connect(gain);
            if (kwargs.pan && context.createStereoPanner) {
                let panner = context.createStereoPanner();
                panner.pan.value = Math.max(-1, Math.min(1, Number(kwargs.pan) / 100));
                gain.connect(panner);
                last = panner;
            }
            last.connect(context.destination);
            source.start();
            if (loops > 1) {
                source.stop(context.currentTime + buffer.duration * loops);
            }
            if (fadein > 0) { fadeTo(gain, volume, fadein); }
            playing[key] = {source: source, gain: gain, name: name,
                            tag: String(kwargs.tag || "")};
            source.onended = function () {
                if (playing[key] && playing[key].source === source) {
                    delete playing[key];
                }
            };
        });
    };

    var stop = function (args, kwargs) {
        kwargs = kwargs || {};
        if (!context) { return; }
        Object.keys(playing).forEach(function (key) {
            let found = playing[key];
            let wanted = (!kwargs.key || kwargs.key === key)
                && (!kwargs.tag || kwargs.tag === found.tag)
                && (!kwargs.name || kwargs.name === found.name);
            if (wanted) { stopOne(key, kwargs.fadeout || 0); }
        });
    };

    var load = function (args, kwargs) {
        if (audio()) { fetchSound(address(kwargs || {})); }
    };

    var onLoggedIn = function () {
        // What Mudlet says when it connects, said the same way.
        window.Evennia.msg("supports_set", ["Client.Media 1"], {});
    };

    var init = function () {
        let Evennia = window.Evennia;
        Evennia.emitter.on("client_media_play", play);
        Evennia.emitter.on("client_media_stop", stop);
        Evennia.emitter.on("client_media_load", load);
        // A browser makes no sound until the page has been used.
        $(document).on("keydown click", function () { audio(); });
        console.log("aimud sound plugin initialized");
    };

    return {
        init: init,
        onLoggedIn: onLoggedIn,
    };
})();
plugin_handler.add("aimud_sound", aimud_sound_plugin);
