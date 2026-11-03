# Focused Window D-Bus, pinned

[flexagoon/focused-window-dbus](https://github.com/flexagoon/focused-window-dbus) at commit
`c70038ebd2a669ae36d578abcb8b332224a88dcf`, MIT licence (`LICENSE`). These are the upstream files,
unchanged; the review is in `docs/third_party_reviews.md`.

`pwi app-usage on` checks them against the reviewed checksums and installs the extension as
`focused-window-dbus-pinned@pwi.local`, with that identifier and a note written into `metadata.json`.
GNOME updates extensions by identifier from extensions.gnome.org, which doesn't know this one, so the
reviewed code is never replaced by an update. To move to a newer upstream version, review it, replace
these files and update the checksums in `service/gnome_extension.py`.
