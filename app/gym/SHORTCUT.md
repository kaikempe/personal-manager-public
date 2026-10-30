# Shortcut "Gym save" (one-time, ~2 minutes, on the iPhone)

The Gym app hands each finished workout to this Shortcut, which writes it into iCloud Drive with no prompts.
The name must be exactly **Gym save**.

1. Shortcuts app > **+** > name it `Gym save`.
2. Add action **Get Dictionary from Input** (input = Shortcut Input, which is the workout JSON as text).
3. Add **Get Dictionary Value**: Get *Value* for `id` in *Dictionary*.
4. Add **Save File**:
   - File: **Shortcut Input**
   - Turn **Ask Where to Save** off
   - Destination: iCloud Drive > Manager Gym > sessions
   - Subpath: the value from step 3, then type `.json` right after it (so the file is `<id>.json`)
   - Turn **Overwrite If File Exists** on
5. First run: iOS asks once to allow Shortcuts to save to that folder. Allow.
6. In the Gym app: Home > tick **Save workouts with the "Gym save" Shortcut**.

Flow: Save workout > Shortcuts opens for a second > back in the app with "Saved to iCloud." If it fails, the
workout stays under "Not saved to Files yet" on Home and can be sent again (the Mac ignores duplicates).
Test it once with a short fake workout, then check that the file appears in Files > Manager Gym > sessions
(the Mac moves it to `done/` within 15 minutes of the LaunchAgent being installed).
