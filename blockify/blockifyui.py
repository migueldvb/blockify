#!/usr/bin/env python2
import codecs
import datetime
import logging
import os
import signal

from dbus.exceptions import DBusException
import blockify
import glib
import gtk
import urllib

# TODO: audio player (toggle, next, prev, shuffle, interactive progress bar)
# TODO: threading for cover art dl
# TODO: toggle button for cover autohide
# TODO: Minimize to system-tray
# TODO: Different modes: minimal, full
# TODO: Textview: Delete line Ctrl+D, Undo/Redo Ctrl+Z, Ctrl+Y
log = logging.getLogger("gui")


class Notepad(gtk.Window):
    "A tiny text editor to modify the blocklist."
    def __init__(self, location, parentw):

        super(Notepad, self).__init__()

        self.location = location
        self.parentw = parentw  # Used to untoggle the open/close list button.

        self.set_title("Blocklist")
        self.set_wmclass("blocklist", "Blockify")
        self.set_default_size(460, 500)
        self.set_position(gtk.WIN_POS_CENTER)

        self.textview = gtk.TextView()
        self.statusbar = gtk.Statusbar()
        self.statusbar.push(0, "Ctrl+S to save, Ctrl+Q/W to close.")

        self.create_keybinds()
        vbox = self.create_layout()

        self.add(vbox)

        self.open_file()
        self.show_all()

        # FIXME: Unholy mess. Why do i have to set value redundantly here?
        swadj = self.sw.get_vadjustment()
        swadj.value = 500
        swadj.set_value(960)

        tvadi = self.textview.get_vadjustment()
        tvadi.value = 500
        tvadi.set_value(960)

    def create_layout(self):
        vbox = gtk.VBox()
        textbox = gtk.VBox()
        statusbox = gtk.VBox()
        vbox.pack_start(textbox, True, True, 0)
        vbox.pack_start(statusbox, False, False, 0)

        # Put the textview into a ScrolledWindow.
        self.sw = gtk.ScrolledWindow()
        self.sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.sw.add(self.textview)
        textbox.pack_start(self.sw)
        statusbox.pack_start(self.statusbar, True, False, 0)

        return vbox

    def create_keybinds(self):
        "Register Ctrl+Q/W to quit and Ctrl+S to save the blocklist."
        quit_group = gtk.AccelGroup()
        quit_group.connect_group(ord("q"), gtk.gdk.CONTROL_MASK,  
                                 gtk.ACCEL_LOCKED, self.destroy)
        quit_group.connect_group(ord("w"), gtk.gdk.CONTROL_MASK,  
                                 gtk.ACCEL_LOCKED, self.destroy)
        self.add_accel_group(quit_group)

        save_group = gtk.AccelGroup()
        save_group.connect_group(ord("s"), gtk.gdk.CONTROL_MASK,
                                 gtk.ACCEL_LOCKED, self.save)
        self.add_accel_group(save_group)

    def destroy(self, *args):
        "Overloading destroy to untoggle the Open List button."
        super(Notepad, self).destroy()
        self.parentw.togglelist.set_active(False)

    def open_file(self, *args):
        textbuffer = self.textview.get_buffer()
        try:
            with codecs.open(self.location, "r", encoding="utf-8") as f:
                textbuffer.set_text(f.read())
        except IOError:
            with codecs.open(self.location, "w", encoding="utf-8"):
                textbuffer.set_text("")
        self.set_title(self.location)

    def save(self, *args):
        textbuffer = self.textview.get_buffer()
        start, end = textbuffer.get_start_iter(), textbuffer.get_end_iter()
        text = textbuffer.get_text(start, end)
        # Append a newline to the blocklist, if necessary.
        if not text.endswith("\n"):
            text += "\n"
        with codecs.open(self.location, "w", encoding="utf-8") as f:
            f.write(text)
        now = str(datetime.datetime.now())
        self.statusbar.push(0, "{}: Saved to {}.".format(now, self.location))


class BlockifyUI(gtk.Window):
    "PyQT4 interface for blockify."
    def __init__(self):
        super(BlockifyUI, self).__init__()
        gtk.threads_init()

        self.automute_toggled = False
        self.block_toggled = False
        self.mute_toggled = False
        self.show_cover = False
        self.autohide_cover = False
        self.editor = None
        # Set the GUI/Blockify update interval to 500ms. Increase this to
        # reduce CPU usage and decrease it to improve responsiveness.
        # If you need absolutely minimal CPU usage you could, in self.start(),
        # change the line to glib.timeout_add_seconds(2, self.update) or more.
        self.update_interval = 500

        self.init_window()

        self.coverimage = gtk.Image()
        self.coverimage.hide_all()
        self.albumlabel = gtk.Label()
        self.artistlabel = gtk.Label()
        self.titlelabel = gtk.Label()
        self.statuslabel = gtk.Label()
        
        for label in [self.albumlabel, self.artistlabel, self.titlelabel]:
#             label.set_line_wrap(True)
            label.set_width_chars(27)

        self.create_buttons()

        self.add(self.create_layout())

        # "Trap" the exit.
        self.connect("destroy", self.stop)

        self.start()
        self.show_all()

    def init_window(self):
        basedir = os.path.dirname(os.path.realpath(__file__))
        self.muteofficon = os.path.join(basedir, "data/not_muted.png")
        self.muteonicon = os.path.join(basedir, "data/muted.png")
        self.adicon = os.path.join(basedir, "data/muted_cover.png")
        self.set_icon_from_file(self.muteofficon)

        # Window setup.
        self.set_title("Blockify")
        self.set_wmclass("blockify", "Blockify")
        self.set_default_size(216, 232)

    def create_buttons(self):
        self.toggleplay = gtk.ToggleButton("Play/Pause")
        self.toggleplay.connect("clicked", self.on_toggleplay)
        self.prevsong = gtk.Button("Previous")
        self.prevsong.connect("clicked", self.on_prevsong)
        self.nextsong = gtk.Button("Next")
        self.nextsong.connect("clicked", self.on_nextsong)
        
        self.toggleblock = gtk.ToggleButton("Block")
        self.toggleblock.connect("clicked", self.on_toggleblock)
        self.checkautoblock = gtk.CheckButton("Automatic")
        self.checkautoblock.connect("clicked", self.on_checkautoblock)

        self.togglemute = gtk.ToggleButton("Mute")
        self.togglemute.connect("clicked", self.on_togglemute)
        self.checkautomute = gtk.CheckButton("Automatic")
        self.checkautomute.connect("clicked", self.on_checkautomute)
        
        self.togglecover = gtk.ToggleButton("Toggle Cover")
        self.togglecover.connect("clicked", self.on_togglecover)
        self.togglecover.set_active(True)
        self.checkautocover = gtk.CheckButton("Automatic")
        self.checkautocover.connect("clicked", self.on_checkautocover)

        self.togglelist = gtk.ToggleButton("Open List")
        self.togglelist.connect("clicked", self.on_togglelist)

    def create_layout(self):
        main = gtk.VBox()
        
        main.add(self.coverimage)
        main.add(self.artistlabel)
        main.add(self.albumlabel)
        main.add(self.titlelabel)
        main.add(self.statuslabel)
        main.add(self.toggleplay)
        
        controlbuttons = gtk.HBox(True)
        controlbuttons.add(self.prevsong)
        controlbuttons.add(self.nextsong)
        main.pack_start(controlbuttons)
        
        blockbuttons = gtk.HBox(True)
        blockbuttons.add(self.toggleblock)
        blockbuttons.add(self.checkautoblock)
        main.pack_start(blockbuttons)
        
        mutebuttons = gtk.HBox(True)
        mutebuttons.add(self.togglemute)
        mutebuttons.add(self.checkautomute)
        main.pack_start(mutebuttons)
        
        coverbuttons = gtk.HBox(True)
        coverbuttons.add(self.togglecover)
        coverbuttons.add(self.checkautocover)
        main.pack_start(coverbuttons)

        main.add(self.togglelist)
        
        return main

    def update(self):
        "Main GUI loop, 500ms update interval (self.update_interval)."
        # Call the main update function of blockify and assign return value
        # (True/False) depending on whether a song to be blocked was found.
        self.found = self.b.update()
        if self.show_cover:
            self.display_cover()

        # Correct the automute state, if necessary.
        if not any([self.mute_toggled, self.automute_toggled, self.b.automute]):
            self.b.automute = True

        # Our main GUI workers here, updating labels, buttons and the likes.
        self.update_songinfo()
        self.update_labels()
        self.update_togglebuttons()

        # The glib.timeout loop will only break if we return False here.
        return True
    
    def get_cover_art(self):
        # The server spotify gets its images from. Filename is a hash, the last part of metadata["artUrl"]
        cover_url = "https://i.scdn.co/image/" + os.path.basename(self.b.dbus.get_art_url())
        cover_file = os.path.join(self.thumbnaildir, os.path.basename(cover_url) + ".png")
         
        if not os.path.exists(cover_file):
            log.info("Downloading cover art: {}".format(cover_file))
            urllib.urlretrieve(cover_url, cover_file)
         
        return cover_file
    
    def display_cover(self):
        if self.b.is_sink_muted or self.b.is_fully_muted:
            if self.autohide_cover:
                self.coverimage.hide()
            else:
                self.coverimage.set_from_file(self.adicon)
        else:
            cover_file = self.get_cover_art()
            pixbuf = gtk.gdk.pixbuf_new_from_file(cover_file)  # @UndefinedVariable
            scaled_buf = pixbuf.scale_simple(195,195,gtk.gdk.INTERP_BILINEAR)  # @UndefinedVariable
            self.coverimage.set_from_pixbuf(scaled_buf)
            if self.autohide_cover:
                self.coverimage.show()

    def update_songinfo(self):
        # Grab some useful information from DBus.
        try:
            self.songstatus = self.b.dbus.get_song_status()
            if self.songstatus:
                self.b.use_dbus = True

        except (DBusException, AttributeError):
            # If we can't get a songstatus, we have to assume DBus is not
            # working correctly.
            self.songstatus = ""
            self.b.use_dbus = False

    def update_labels(self):
        if self.b.dbus and self.b.use_dbus:
            self.statuslabel.set_text(self.get_status_text())
            if self.b.current_song_is_ad():
                self.albumlabel.hide()
            else:
                self.albumlabel.show()
                self.albumlabel.set_text(self.b.dbus.get_song_album())

        artist, title = self.format_current_song()
        self.artistlabel.set_text(artist)
        self.titlelabel.set_text(title)

    def update_togglebuttons(self):
        # Correct the state of the Block/Unblock toggle button.
        if self.found:
            self.toggleblock.set_active(True)
        elif not self.found:
            self.toggleblock.set_active(False)

        # Correct state of Open/Close List toggle button.
        if self.editor:
            if not self.editor.get_visible() and self.togglelist.get_active():
                self.togglelist.set_active(False)

    def format_current_song(self):
        song = self.b.current_song
        # For whatever reason, Spotify doesn't use a normal hyphen but a
        # slightly longer one. This is its unicode code point.
        delimiter = u"\u2013"  # \xe2\x80\x93 is the bytestring.

        # We prefer the current_song variable as source for artist, title but
        # should that fail, try getting those from DBus.
        try:
            artist, title = song.split(" {} ".format(delimiter))
        except (ValueError, IndexError):
            try:
                artist = self.b.dbus.get_song_artist()
                title = self.b.dbus.get_song_title()
            except (DBusException, AttributeError):
                artist = title = None

        # Sometimes song.split returns None, catch it here.
        if artist is None or title is None:
            artist, title = song, "No song playing?"
            self.b.use_dbus = False

        return artist, title

    def get_status_text(self):
        status = ""
        if self.b.dbus and self.b.use_dbus:
            try:
                songlength = self.b.dbus.get_song_length()
            except (TypeError, DBusException) as e:
                log.error("Cannot use DBus. Some features (PlayPause etc.)"
                          " will be unavailable ({}).".format(e))
                return status

            if songlength:
                m, s = divmod(songlength, 60)
                r = self.b.dbus.get_property("Metadata")["xesam:autoRating"]
                status = "{}m{}s, {} ({})".format(m, s, r, self.songstatus)

        return status

    def start(self):
        "Start blockify and the main update routine."
        # Load the blocklist, start blockify, trap some signals and unmute.
        blocklist = blockify.Blocklist(blockify.get_configdir())
        self.b = blockify.Blockify(blocklist)
        self.thumbnaildir = os.path.join(self.b.configdir, "thumbnails")
        self.bind_signals()
        self.b.toggle_mute()
        # Start and loop the main update routine once every 250ms.
        # To influence responsiveness or CPU usage, decrease/increase ms here.
#         glib.timeout_add_seconds(1, self.update)
        glib.timeout_add(self.update_interval, self.update)  # @UndefinedVariable
        # Initially correct the state of the autodetect button.
        if self.b.autodetect:
            self.checkautoblock.set_active(True)
        log.info("Blockify-UI started.")

    def bind_signals(self):
        "Binds SIGTERM, SIGINT and SIGUSR1 to custom actions."
        signal.signal(signal.SIGUSR1, lambda sig, hdl: self.b.block_current())
        signal.signal(signal.SIGUSR2, lambda sig, hdl: self.b.unblock_current())
        signal.signal(signal.SIGTERM, lambda sig, hdl: self.stop())
        signal.signal(signal.SIGINT, lambda sig, hdl: self.stop())

    def stop(self, *args):
        "Cleanly shut down, unmuting sound and saving the blocklist."
        self.b.stop()
        log.debug("Exiting GUI.")
        gtk.main_quit()
        
    def restore_size(self):
        width, height = self.get_default_size()
        self.resize(width, height)
        
    def enable_cover(self):
        if not self.coverimage.flags() & gtk.VISIBLE:
            self.show_cover = True
            self.coverimage.show()
    
    def disable_cover(self):
        if self.coverimage.flags() & gtk.VISIBLE:
            self.show_cover = False
            self.coverimage.hide()
            self.restore_size()
        
    def on_togglecover(self, widget):
        if widget.get_active():
            widget.set_label("Hide Cover")
            self.enable_cover()
            log.info("Enabled cover art.")
        else:
            widget.set_label("Show Cover")
            self.disable_cover()
            log.info("Disabled cover art.")
    
    def on_checkautocover(self, widget):
        if widget.get_active():
            self.autohide_cover = True
        else:
            self.autohide_cover = False

    def on_toggleblock(self, widget):
        # Block the blockbutton if blockbutton-blocking togglebuttons are toggled.
        if self.automute_toggled or self.mute_toggled:
            return
        if widget.get_active():
            widget.set_label("Unblock")
            if not self.found:
                self.b.block_current()
            if not self.block_toggled:
                self.set_icon_from_file(self.muteonicon)
                self.set_title("Blockify (blocked)")
                self.block_toggled = True
        else:
            widget.set_label("Block")
            if self.found:
                self.b.unblock_current()
            # Only
            if self.block_toggled:
                self.set_icon_from_file(self.muteofficon)
                self.set_title("Blockify")
                self.block_toggled = False

    def on_checkautomute(self, widget):
        if widget.get_active():
            self.set_title("Blockify (inactive)")
            self.b.automute = False
            self.automute_toggled = True
            self.block_toggled = False
            widget.set_label("Enable AutoMute")
            if not self.mute_toggled:
                self.b.toggle_mute()
                lbl = self.toggleblock.get_label()
                self.toggleblock.set_label(lbl + " (disabled)")
        else:
            self.set_title("Blockify")
            self.b.automute = True
            self.automute_toggled = False
            widget.set_label("Disable AutoMute")
            if not self.mute_toggled:
                self.toggleblock.set_label("Block")

    def on_checkautoblock(self, widget):
        if widget.get_active():
            if not self.b.dbus:
                self.b.connect_dbus()
                self.albumlabel.hide()
            self.b.try_enable_dbus()
            widget.set_label("Automatic")
            log.info("Enabled ad autodetection.")
        else:
            widget.set_label("Enable Autodetection")
            self.b.autodetect = False
            log.info("Disabled ad autodetection.")

    def on_togglemute(self, widget):
        if self.block_toggled:
            return
        if widget.get_active():
            widget.set_label("Unmute")
            self.set_icon_from_file(self.muteonicon)
            self.b.automute = False
            self.mute_toggled = True
            self.b.toggle_mute(1)
            if not self.automute_toggled:
                self.set_title("Blockify (muted)")
                lbl = self.toggleblock.get_label()
                self.toggleblock.set_label(lbl + " (disabled)")
        else:
            widget.set_label("Mute")
            self.set_icon_from_file(self.muteofficon)
            self.mute_toggled = False
            self.b.toggle_mute(2)
            if not self.automute_toggled:
                self.b.automute = True
                self.set_title("Blockify")
                self.toggleblock.set_label("Block")

    def on_togglelist(self, widget):
        if widget.get_active():
            widget.set_label("Close List")
            self.editor = Notepad(self.b.blocklist.location, self)
        else:
            widget.set_label("Open List")
            if self.editor:
                self.editor.destroy()

    def on_toggleplay(self, widget):
        # Try to connect to DBus if it failed before.
        if not self.b.dbus:
            self.connect_dbus()
        if self.b.dbus and self.b.use_dbus:
            if self.songstatus == "Playing":
                widget.set_label("Play")
            else:
                widget.set_label("Pause")
            self.b.dbus.playpause()

    def on_nextsong(self, widget):
        if not self.b.dbus:
            self.b.connect_dbus()
        if self.b.dbus and self.b.use_dbus:
            self.b.dbus.next()

    def on_prevsong(self, widget):
        if not self.b.dbus:
            self.b.connect_dbus()
        if self.b.dbus and self.b.use_dbus:
            self.b.dbus.prev()


def main():
    "Entry point for the GUI-version of Blockify."
    # Edit this for less or more logging. Loglevel 0 is least verbose.
    blockify.init_logger(logpath=None, loglevel=2, quiet=False)
    BlockifyUI()
    gtk.main()


if __name__ == "__main__":
    main()
