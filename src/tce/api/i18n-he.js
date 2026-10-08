/* Hebrew UI for a Hebrew workspace (5-Oct). Loaded ONLY when the page is served to
 * a login whose workspace language is "he" (see dashboard.py); the owner's pages
 * never reference this file, so they stay byte for byte as they were.
 *
 * It translates the interface, never the content: an exact English UI string, or
 * one of the patterns below, becomes Hebrew. Script text, titles and notes are
 * already Hebrew and match no key, so they pass through untouched. The pages
 * render a lot of their text at runtime, so a MutationObserver translates what
 * they write as they write it. */
(function (root) {
  "use strict";

  var EXACT = {
    // Navigation and frame
    "Today": "היום",
    "Topics": "נושאים",
    "This week": "השבוע",
    "Record": "הקלטה",
    "Library": "ספרייה",
    "Settings": "הגדרות",
    "Sections": "אזורים",
    "Back to KM BOT": "חזרה ל-KM BOT",
    "Back to Today": "חזרה להיום",
    "Talk with TCE": "לדבר עם TCE",
    "Loading": "טוען",
    "Opening your workspace": "פותח את סביבת העבודה שלך",
    "Editorial workspace": "סביבת העבודה שלך",
    "TCE Recording Studio": "אולפן ההקלטות",

    // Recording studio: queue and opening step
    "Walking studio": "אולפן הליכה",
    "Loading your scripts": "טוען את התסריטים שלך",
    "This recording sitting": "ההקלטה של עכשיו",
    "Ready to record": "מוכן להקלטה",
    "Tap one and the camera opens. Each idea keeps its own clips, so you can move between scripts without losing a take.":
      "בוחרים אחד והמצלמה נפתחת. לכל רעיון יש קליפים משלו, אז אפשר לעבור בין תסריטים בלי לאבד אף טייק.",
    "Nothing is ready to record yet": "עדיין אין משהו מוכן להקלטה",
    "Choose your topics in Topics and prepare their scripts from This week.":
      "בוחרים נושאים בלשונית נושאים ומכינים להם תסריט מתוך השבוע.",
    "Step 1 of 2": "שלב 1 מתוך 2",
    "Choose how it opens": "בוחרים איך זה נפתח",
    "The first spoken line. Everything after it stays the same.": "המשפט הראשון שאומרים. כל מה שאחריו נשאר אותו דבר.",
    "Ask for more openings": "עוד פתיחות",
    "Choose the opening": "בוחרים פתיחה",
    "Pick the first spoken line. The rest of the script stays the same.":
      "בוחרים את המשפט הראשון. שאר התסריט נשאר אותו דבר.",
    "Choose another opening, or fix the line in the script first.": "בוחרים פתיחה אחרת, או מתקנים קודם את המשפט בתסריט.",
    "Creating the packet version with this opening": "מכין גרסה עם הפתיחה הזאת",
    "Recommended": "מומלץ",
    "Use this opening": "להשתמש בפתיחה הזאת",
    "Open the script": "לפתוח את התסריט",
    "That script is not ready to record yet. Here is what is.": "התסריט הזה עוד לא מוכן להקלטה. הנה מה שכן מוכן.",
    "Could not load scripts": "לא הצלחתי לטעון את התסריטים",

    // Recording studio: camera and teleprompter
    "Front camera": "מצלמה קדמית",
    "Camera and microphone start only when you press Record.": "המצלמה והמיקרופון נדלקים רק כשלוחצים הקלטה.",
    "Recording": "מקליט",
    "Recording interrupted. Check the camera before continuing.": "ההקלטה נקטעה. כדאי לבדוק את המצלמה לפני שממשיכים.",
    "Points": "נקודות",
    "Full script": "תסריט מלא",
    "Reader mode": "מצב קריאה",
    "Jump to a point": "קפיצה לנקודה",
    "Next points": "הנקודות הבאות",
    "Earlier points": "הנקודות הקודמות",
    "Swap words and video": "להחליף בין הטקסט לווידאו",
    "Words over the video": "טקסט על הווידאו",
    "Text size": "גודל טקסט",
    "Bigger text": "טקסט גדול יותר",
    "Smaller text": "טקסט קטן יותר",
    "Darker background": "רקע כהה יותר",
    "Lighter background": "רקע בהיר יותר",
    "Opening": "פתיחה",
    "Change": "להחליף",
    "Recording controls": "כפתורי הקלטה",
    "Pause": "השהיה",
    "Resume": "המשך",
    "Stop": "עצור",
    "keep this take": "שומרים את הטייק",
    "Finish": "סיום",
    "send for editing": "שולחים לעריכה",
    "Paused. The current clip is still open.": "מושהה. הקליפ הנוכחי עדיין פתוח.",
    "Clip saved and checked for camera and microphone tracks.": "הקליפ נשמר, ויש בו תמונה וקול.",
    "Nothing recorded yet, so there is nothing to send for editing.": "עוד לא הוקלט כלום, אז אין מה לשלוח לעריכה.",
    "Assembling clips and checking audio": "מחבר את הקליפים ובודק את הקול",
    "Sending a clip that did not get through before": "שולח קליפ שלא עבר קודם",
    "Sending the end of the last clip before building the video": "שולח את סוף הקליפ האחרון לפני שבונים את הסרטון",
    "Session saved as one editable recording. Every source clip is retained.":
      "ההקלטה נשמרה כקובץ אחד לעריכה. כל הקליפים המקוריים נשמרו.",
    "Save this clip before switching?": "לשמור את הקליפ לפני שעוברים?",
    "The clip will stay with this script. The next script opens as soon as the bytes are safe on this phone.":
      "הקליפ יישאר עם התסריט הזה. התסריט הבא ייפתח ברגע שהקליפ שמור בטלפון.",
    "Stay here": "להישאר כאן",
    "Save clip and switch": "לשמור ולעבור",
    // Finish, once (8-Oct): the note and the progress card on the list
    "Sending your take for editing": "שולחים את הטייק לעריכה",
    "This carries on in the background. In a moment you are back on your list, with its progress at the top.":
      "זה ממשיך ברקע. עוד רגע חוזרים לרשימה, וההתקדמות מופיעה למעלה.",
    "The take you just sent": "הטייק ששלחת עכשיו",
    "Hide this": "להסתיר",
    "Your take": "הטייק שלך",
    "Put it together again": "לחבר שוב",
    "See it in the Library": "לראות בספרייה",
    "Sending the last clip from this phone": "שולחים את הקליפ האחרון מהטלפון",
    "Sending the last clip from this phone.": "שולחים את הקליפ האחרון מהטלפון.",
    "Putting the clips together and checking the sound": "מחברים את הקליפים ובודקים את הקול",
    "Putting the clips together and checking the sound.": "מחברים את הקליפים ובודקים את הקול.",
    "Editing the video": "עורכים את הסרטון",
    "Editing the video.": "עורכים את הסרטון.",
    "Please stay on this screen: sending the end of your last clip from this phone.":
      "נא להישאר במסך הזה: שולחים את סוף הקליפ האחרון מהטלפון.",
    "Please stay on this screen: sending a clip that did not get through before.":
      "נא להישאר במסך הזה: שולחים קליפ שלא עבר קודם.",
    "Being put together for editing": "מחברים לעריכה",
    "Handing the clips to TCE.": "מעבירים את הקליפים ל-TCE.",
    "Putting the clips together and checking the sound. You do not have to wait for this.":
      "מחברים את הקליפים ובודקים את הקול. לא צריך לחכות לזה.",
    "Saved as one video. The edit starts in a moment.": "נשמר כסרטון אחד. העריכה מתחילה עוד רגע.",
    "Edited. It is waiting for you in the Library.": "נערך. הוא מחכה לך בספרייה.",
    "This take was replaced by a newer version.": "הטייק הזה הוחלף בגרסה חדשה יותר.",
    "The edit stopped. Open it in the Library to see why.": "העריכה נעצרה. אפשר לפתוח בספרייה ולראות למה.",
    "The video was not put together. Press the button below to try again.":
      "הסרטון לא חובר. אפשר ללחוץ על הכפתור למטה ולנסות שוב.",
    "Could not check on it just now. Trying again in a moment.": "לא הצלחנו לבדוק כרגע. ננסה שוב עוד רגע.",

    // Workspace: pages, headings, buttons
    "Start recording": "להתחיל להקליט",
    "Topic": "נושא",
    "No script yet": "עוד אין תסריט",
    "Script ready": "התסריט מוכן",
    "Post": "פוסט",
    "Opening the conversation": "פותח את השיחה",
    "Needs you": "מחכה לך",
    "Needs you.": "מחכה לך.",
    "Done.": "בוצע.",
    "Done": "בוצע",
    "Ask for a rewrite": "לבקש שכתוב",
    "Your request is done": "הבקשה שלך בוצעה",
    "Your notes on this video": "ההערות שלך על הסרטון",
    "Your angle": "הזווית שלך",
    "You": "אתה",
    "Written by you.": "נכתב על ידך.",
    "Working on your request": "עובד על הבקשה שלך",
    "Working on it.": "עובד על זה.",
    "Why this is yours": "למה זה שלך",
    "Why now": "למה עכשיו",
    "Who it helps": "למי זה עוזר",
    "When to post": "מתי לפרסם",
    "What to ask for": "מה לבקש",
    "What they should take away": "מה הם צריכים לקחת מזה",
    "Use the new version": "להשתמש בגרסה החדשה",
    "Undone.": "בוטל.",
    "Undo": "ביטול",
    "Type instead of talking": "להקליד במקום לדבר",
    "Title": "כותרת",
    "This week's list": "הרשימה של השבוע",
    "This idea": "הרעיון הזה",
    "The point": "הנקודה",
    "The engine is not available right now.": "המנוע לא זמין כרגע.",
    "Talk it through first": "קודם לדבר על זה",
    "Talk about this week": "לדבר על השבוע",
    "Talk about this topic": "לדבר על הנושא",
    "Talk about this script": "לדבר על התסריט",
    "Talk about this": "לדבר על זה",
    "Talk about the whole week": "לדבר על כל השבוע",
    "Sending": "שולח",
    "Send": "שליחה",
    "Script being written": "התסריט נכתב",
    "Script": "תסריט",
    "Scheduled": "מתוזמן",
    "Say something first.": "קודם להגיד משהו.",
    "Saving": "שומר",
    "Save": "שמירה",
    "Restore": "שחזור",
    "Restoring": "משחזר",
    "Record it this week": "להקליט השבוע",
    "Ready to post": "מוכן לפרסום",
    "Reading your week": "קורא את השבוע שלך",
    "Reading your settings": "קורא את ההגדרות שלך",
    "Reading your notes back": "קורא את ההערות שלך",
    "Reading what you have recorded": "קורא מה שהקלטת",
    "Reading this week's list": "קורא את הרשימה של השבוע",
    "Reading the ideas waiting for you": "קורא את הרעיונות שמחכים לך",
    "Put back": "להחזיר",
    "Proposed change": "שינוי מוצע",
    "Prepare the script": "להכין תסריט",
    "Posted": "פורסם",
    "Posting now": "מפרסם עכשיו",
    "Point": "נקודה",
    "Pick one, or say what you want changed.": "בוחרים אחד, או אומרים מה לשנות.",
    "Parts of the script": "חלקי התסריט",
    "Outline": "שלד",
    "Or say exactly what you want changed...": "או להגיד בדיוק מה לשנות...",
    "Opening the topic": "פותח את הנושא",
    "Opening the script": "פותח את התסריט",
    "Openings": "פתיחות",
    "One more": "עוד אחד",
    "One fewer": "אחד פחות",
    "Not this week, keep as a spare": "לא השבוע, לשמור ברזרבה",
    "Nothing said yet": "עוד לא נאמר כלום",
    "No ideas match this filter.": "אין רעיונות שמתאימים לסינון.",
    "Make it sound more like me": "שיישמע יותר כמוני",
    "Make it shorter": "לקצר",
    "Make it more practical": "יותר פרקטי",
    "Make it more opinionated": "יותר דעתני",
    "Make it less corporate": "פחות תאגידי",
    "Line": "שורה",
    "Jennifer's rules": "הכללים של ג'ניפר",
    "Jennifer has a question.": "לג'ניפר יש שאלה.",
    "In this week's list.": "ברשימה של השבוע.",
    "In the reserve list.": "ברשימת הרזרבה.",
    "Give notes on the new version": "הערות על הגרסה החדשה",
    "Filter topics": "סינון נושאים",
    "Filter recordings": "סינון הקלטות",
    "Everything you have recorded, and what happened to it.": "כל מה שהקלטת, ומה קרה איתו.",
    "Edit": "עריכה",
    "Download the edit": "להוריד את העריכה",
    "Download": "הורדה",
    "Did not go out": "לא יצא",
    "Description": "תיאור",
    "Could not load": "לא הצלחתי לטעון",
    "Choose when to post first.": "קודם בוחרים מתי לפרסם.",
    "Choose this week's topics": "לבחור את הנושאים של השבוע",
    "Caption": "כיתוב",
    "Being changed": "בשינוי",
    // His post card (5-Oct): download the finished video, copy each post.
    "Your video and posts": "הסרטון והפוסטים שלך",
    "Ready to copy": "מוכן להעתקה",
    "Copy": "העתקה",
    "Copied": "הועתק",
    "Copied. Paste it in the app.": "הועתק. מדביקים באפליקציה.",
    "Could not copy. Select the text and copy it yourself.": "ההעתקה לא הצליחה. מסמנים את הטקסט ומעתיקים ידנית.",
    "Tags (comma separated)": "תגיות (מופרדות בפסיק)",
    "Write the posts": "לכתוב את הפוסטים",
    "Write them again": "לכתוב אותם מחדש",
    "Change the posts": "לשנות את הפוסטים",
    "Ask for a change to the posts": "לבקש שינוי בפוסטים",
    "For example: shorter, and open with the question": "למשל: יותר קצר, ולפתוח בשאלה",
    "Writing your posts. This card fills in when they are ready.": "כותב את הפוסטים שלך. הכרטיס יתמלא כשהם מוכנים.",
    "Writing the posts on your subscription. This card fills in when they are ready.": "כותב את הפוסטים. הכרטיס יתמלא כשהם מוכנים.",
    "Changing the posts on your subscription. This card updates when they are ready.": "משנה את הפוסטים. הכרטיס יתעדכן כשהם מוכנים.",
    "Say what should change first.": "קודם להגיד מה לשנות.",
    // The worker line on Today (content_runs worker status).
    "No subscription worker has reported in the last 3 minutes. Jobs start when the desktop worker checks in.":
      "המחשב שכותב את התוכן לא דיווח ב-3 הדקות האחרונות. העבודה תתחיל כשהוא יתחבר.",
    "All your ideas and this week": "כל הרעיונות שלך והשבוע",
    "Talk to Jennifer": "לדבר עם ג'ניפר",
    "Close the conversation": "לסגור את השיחה",
    "Close the notes. They stay saved.": "לסגור את ההערות. הן נשמרות.",
    "What this conversation may do": "מה השיחה הזאת יכולה לעשות",
    "Discuss": "לדבר",
    "Propose changes": "להציע שינויים",
    "Say what you think. Nothing changes unless you accept it.": "תגיד מה אתה חושב. שום דבר לא משתנה בלי שתאשר.",
    "Read replies out loud": "להקריא את התשובות",
    "Read aloud": "הקראה",
    "Replies will be read out loud.": "התשובות יוקראו בקול.",
    "Replies stay silent.": "התשובות לא יוקראו.",
    "Checking again every few seconds": "בודק שוב כל כמה שניות",
    "Your next useful action.": "הצעד הבא שלך.",
    "scripts ready": "תסריטים מוכנים",
    "need a decision": "מחכים להחלטה",
    "changes to review": "שינויים לבדיקה",
    "being edited": "בעריכה",
    "This week's recording list": "רשימת ההקלטות של השבוע",
    "Notifications are blocked in your browser settings.": "ההתראות חסומות בהגדרות הדפדפן.",
    "Type": "הקלדה",
    "Pause where something is wrong, then tap Type to write a note.":
      "עוצרים במקום שמשהו לא בסדר, ולוחצים על הקלדה כדי לכתוב הערה.",
    "is first.": "ראשון בתור.",
    "Record this one": "להקליט את זה",
    "Open the topic": "לפתוח את הנושא",
    "Open it": "לפתוח",
    "Record first": "קודם להקליט",
    "Start a new take set": "הקלטה חדשה",
    "Best matches": "הכי מתאימים",
    "Calls": "שיחות",
    "Code": "קוד",
    "AI news": "חדשות AI",
    "Evergreen": "תמיד רלוונטי",
    "Later": "אחר כך",
    "Put away": "בצד",
    "Change how many a week": "לשנות כמה בשבוע",
    "Take out of the week": "להוציא מהשבוע",
    "Still to do": "עוד לעשות",
    "Uploading": "מעלה",
    "Being edited": "בעריכה",
    "Needs your review": "מחכה לבדיקה שלך",
    "Ready": "מוכן",
    "Published": "פורסם",
    "Everything": "הכול",
    "Archived": "בארכיון",
    "Videos a week": "סרטונים בשבוע",
    "Open this week": "לפתוח את השבוע",
    "How your posts read": "איך הפוסטים שלך נשמעים",
    "Your post rules": "הכללים לפוסטים שלך",
    "Save the rules": "לשמור את הכללים",
    "Notifications": "התראות",
    "Keep this opening": "להשאיר את הפתיחה הזאת",
    "Decide what is worth your time. Nothing here asks the engine for anything.": "מחליטים מה שווה את הזמן שלך. שום דבר כאן לא מפעיל את המנוע.",
    "Nothing here": "אין כאן כלום",
    "Everything is decided. The next weekly run collects new evidence.": "הכול הוחלט. הסבב השבועי הבא יביא רעיונות חדשים.",
    "The order here is the order you record in.": "הסדר כאן הוא סדר ההקלטה.",
    "What still needs you: recorded, being edited, or waiting to go out.": "מה שעוד מחכה לך: הוקלט, בעריכה, או מחכה לצאת.",
    ": what she learned from your notes, and applies to every next video.": ": מה שהיא למדה מההערות שלך, ומיישמת בכל סרטון הבא.",
    "Nothing waiting on you": "שום דבר לא מחכה לך",
    "Everything you recorded has gone out. Published videos are under Published.": "כל מה שהקלטת כבר יצא. סרטונים שפורסמו נמצאים תחת פורסם.",
    "How many videos you usually record in a week. Each new week starts with this many places, and this week changes too.": "כמה סרטונים אתה מקליט בדרך כלל בשבוע. כל שבוע חדש מתחיל עם מספר המקומות הזה, וגם השבוע הנוכחי משתנה.",
    "Had a good week? Put more in the week anyway. This number is your usual week, not a limit.": "היה שבוע טוב? אפשר להכניס עוד לשבוע. המספר הזה הוא השבוע הרגיל שלך, לא תקרה.",
    "Every post TCE writes for you follows this, in your words. Change it any time; the next posts follow the new version.": "כל פוסט ש-TCE כותב בשבילך הולך לפי זה, במילים שלך. אפשר לשנות מתי שרוצים; הפוסטים הבאים ילכו לפי הגרסה החדשה.",
    "Other": "אחר",

    // 6-Oct: every screen of his login, walked at 390px and 1280px
    // (tests/unit/test_matan_every_screen_hebrew.py). Today and its next step (today.py).
    "Find more ideas": "למצוא עוד רעיונות",
    "Nothing is waiting. Every idea this week's evidence produced is decided.":
      "אין רעיונות שמחכים. על כל הרעיונות של השבוע כבר החלטת.",
    "Nothing chosen yet": "עוד לא נבחר כלום",
    "Pick the topics worth recording and they appear here, in order.":
      "בוחרים את הנושאים ששווה להקליט, והם יופיעו כאן לפי הסדר.",
    "Choose topics": "לבחור נושאים",
    "Review proposed changes": "לעבור על השינויים המוצעים",
    "Prepare this week's scripts": "להכין את התסריטים של השבוע",
    "Your script is on the way": "התסריט שלך בדרך",
    "Your scripts are on the way": "התסריטים שלך בדרך",
    "Each one is written on your PC worker.": "כל תסריט נכתב אוטומטית.",
    "Changes by voice": "שינויים בקול",
    "What the voice agent changed in the last 24 hours, newest first. Undo takes one back and keeps both versions in the history.":
      "מה שהסוכן הקולי שינה ב-24 השעות האחרונות, מהחדש לישן. ביטול מחזיר שינוי אחד ושומר את שתי הגרסאות בהיסטוריה.",
    "This put an earlier change back.": "זה החזיר שינוי קודם.",
    "Undoing": "מבטל",
    "Brought back.": "הוחזר.",
    "This workspace refused the request.": "סביבת העבודה סירבה לבקשה.",
    "Could not open this": "לא הצלחתי לפתוח את זה",

    // Topics and the topic page
    "Script written": "התסריט נכתב",
    "Set aside by the engine: a newer run replaced it, or its news went stale. Putting it in the week brings it back.":
      "המנוע הניח את זה בצד: סבב חדש יותר החליף אותו, או שהחדשות שלו כבר לא טריות. הכנסה לשבוע מחזירה אותו.",
    "Put in this week": "להכניס לשבוע",
    "Save for later": "לשמור לאחר כך",
    "Put it away": "להניח בצד",
    "Marked to think about.": "סומן לחשוב עליו.",
    "Saved for later. It will not be offered again until you ask.": "נשמר לאחר כך. הוא לא יוצע שוב עד שתבקש.",
    "Put away. It will not be offered again.": "הונח בצד. הוא לא יוצע שוב.",
    "Timely": "אקטואלי",
    "The topic": "הנושא",
    "The script": "התסריט",
    "The thinking": "החשיבה",
    "Change any block yourself. Every change is shown as a before and after before it is kept, and every version stays in the history.":
      "אפשר לשנות כל חלק בעצמך. כל שינוי מוצג כלפני ואחרי לפני שהוא נשמר, וכל גרסה נשארת בהיסטוריה.",
    "Read and change the script": "לקרוא ולשנות את התסריט",
    "History": "היסטוריה",
    "Go back to this version": "לחזור לגרסה הזאת",
    "Arranged from the idea as the engine proposed it.": "סודר מהרעיון כמו שהמנוע הציע.",
    "Changed by you.": "שונה על ידך.",
    "Restored from an earlier version.": "שוחזר מגרסה קודמת.",
    "What it rests on": "על מה זה נשען",
    "Claims to avoid": "טענות שכדאי להימנע מהן",
    "Nothing written yet.": "עוד לא נכתב כלום.",
    "Cancel": "ביטול",
    "Tie it harder to coaching": "לקשור יותר לאימון",
    "Take the sales angle out": "להוציא את זווית המכירה",
    "Ask for it": "לבקש",
    "That is what it already says.": "זה בדיוק מה שכבר כתוב.",
    "Before": "לפני",
    "After": "אחרי",
    "Keep what I have": "להשאיר מה שיש",
    "Saving the new version": "שומר את הגרסה החדשה",
    "Saved. The previous version is in the history.": "נשמר. הגרסה הקודמת בהיסטוריה.",
    "Kept what you had.": "נשאר מה שהיה.",
    "Talk about the ideas as a set, before you pick one. Which of these is actually strongest? Is the mix wrong? Does any of this say what I really do? Nothing here changes a topic.":
      "מדברים על כל הרעיונות ביחד, לפני שבוחרים אחד. איזה מהם באמת הכי חזק? התמהיל לא נכון? משהו מזה אומר מה אני באמת עושה? שום דבר כאן לא משנה נושא.",
    "Think out loud. In Discuss nothing changes, whatever you ask for.": "חושבים בקול. בשיחה שום דבר לא משתנה, מה שלא תבקש.",
    "Thinking about this.": "חושב על זה.",
    "That turn did not finish.": "התשובה לא הסתיימה.",
    "Review the change": "לבדוק את השינוי",
    "Asked. The script is written on your PC worker; it takes a few minutes.": "ביקשת. התסריט נכתב עכשיו; זה לוקח כמה דקות.",
    "The script is written on your PC worker and takes a few minutes.": "התסריט נכתב אוטומטית וזה לוקח כמה דקות.",
    "Restored. It is saved as a new version, so nothing was lost.": "שוחזר. זה נשמר כגרסה חדשה, אז שום דבר לא אבד.",

    // This week
    "Possible replacements": "מחליפים אפשריים",
    "Ready to swap in, or add to the week if it is a good one.": "מוכנים להיכנס במקום, או להתווסף לשבוע אם הם טובים.",
    "Filmed": "צולם",
    "Make first": "להעביר לראש",
    "Move up": "להעלות",
    "Move down": "להוריד",
    "In reserve.": "ברזרבה.",
    "Build": "בנייה",
    "Coaching": "אימון",

    // Script requests (status.py): a script asked for, on its way, or stuck
    "Script asked for": "התבקש תסריט",
    "Script waiting for your Claude limit": "התסריט מחכה שהמנוי יתחדש",
    "Waiting for your Claude limit to reset": "מחכה שהמנוי יתחדש",
    "Waiting for the PC worker": "מחכה למחשב שכותב",
    "New script kept aside": "התסריט החדש נשמר בצד",
    "New script on its way": "תסריט חדש בדרך",
    "Script not saved": "התסריט לא נשמר",
    "Script written, saving it": "התסריט נכתב, שומר אותו",
    "Script request lost": "הבקשה לתסריט אבדה",
    "Script request stopped": "הבקשה לתסריט נעצרה",
    "Asked for. It is written on your PC worker and saves itself when it is done.": "התבקש. התסריט נכתב אוטומטית ונשמר לבד כשהוא מוכן.",
    "Written. It is saved within five minutes, without a new model call.": "נכתב. הוא יישמר תוך חמש דקות.",
    "Ask for it again: it is saved without a new model call.": "אפשר לבקש שוב: הוא יישמר בלי לכתוב מחדש.",
    "You filmed this topic after asking for a new script, so the new one is kept aside and the script you filmed stays.":
      "צילמת את הנושא אחרי שביקשת תסריט חדש, אז החדש נשמר בצד והתסריט שצילמת נשאר.",
    "Written, but the request that asked for it is lost. Ask for a new script.": "נכתב, אבל הבקשה אבדה. אפשר לבקש תסריט חדש.",
    "The script came back incomplete and was not saved. Ask for a new script.": "התסריט חזר חלקי ולא נשמר. אפשר לבקש תסריט חדש.",

    // Script workshop
    "Script workshop": "סדנת התסריט",
    "Post versions": "גרסאות לפוסטים",
    "Three at a time. Asking for more re-ranks them rather than making the list longer.":
      "שלוש בכל פעם. בקשה לעוד מדרגת אותן מחדש, ולא מאריכה את הרשימה.",
    "This is the one you open with": "בזה אתה פותח",
    "Locked: this script has been recorded": "נעול: התסריט הזה כבר הוקלט",
    "No openings yet": "עוד אין פתיחות",
    "They are written with the script.": "הן נכתבות יחד עם התסריט.",
    "Ask for different openings": "לבקש פתיחות אחרות",
    "Not written.": "לא נכתב.",
    "Nothing here yet": "עוד אין כאן כלום",
    "This part of the script has not been written.": "החלק הזה של התסריט עוד לא נכתב.",
    "Asked. New openings are written on your PC worker; it takes a few minutes.": "ביקשת. פתיחות חדשות נכתבות עכשיו; זה לוקח כמה דקות.",

    // Settings and notifications
    "Notifications are not available on this device.": "התראות לא זמינות במכשיר הזה.",
    "Saved. The next posts follow these rules.": "נשמר. הפוסטים הבאים ילכו לפי הכללים האלה.",
    "Notifications are on for this device.": "ההתראות פועלות במכשיר הזה.",
    "Turn off": "לכבות",
    "Turn on notifications on this phone": "להפעיל התראות בטלפון הזה",
    "New topics you asked for, scripts and edits: a buzz when each is ready.": "נושאים חדשים שביקשת, תסריטים ועריכות: התראה כשכל אחד מוכן.",
    "This browser cannot do notifications.": "הדפדפן הזה לא תומך בהתראות.",
    "On iPhone, add this page to your Home Screen first (Share, then Add to Home Screen). Notifications only work from there.":
      "באייפון צריך קודם להוסיף את הדף למסך הבית (שיתוף, ואז הוספה למסך הבית). התראות עובדות רק משם.",
    "Push is not configured on the server.": "התראות לא מוגדרות בשרת.",
    "Left off.": "נשאר כבוי.",
    "On. You will get a buzz when a script or an edit is ready.": "פועל. תקבל התראה כשתסריט או עריכה מוכנים.",
    "Off.": "כבוי.",

    // Library: cards, states and actions (library.py, workspace.js)
    "Nothing archived": "אין כלום בארכיון",
    "A recording you archive, or choose not to edit after a talk, waits here.": "הקלטה שהעברת לארכיון, או שבחרת לא לערוך, מחכה כאן.",
    "Nothing published yet": "עוד לא פורסם כלום",
    "A video moves here once one of its posts goes out or is scheduled.": "סרטון עובר לכאן ברגע שאחד הפוסטים שלו יוצא או מתוזמן.",
    "Nothing recorded yet": "עוד לא הוקלט כלום",
    "Recordings appear here as soon as the studio finishes uploading them.": "הקלטות מופיעות כאן ברגע שהאולפן מסיים להעלות אותן.",
    "Videos that have gone out, or are scheduled to.": "סרטונים שיצאו, או שמתוזמנים לצאת.",
    "Recordings you set aside. Nothing here is edited or posted. Edit this now starts the edit of one that was never edited.":
      "הקלטות שהנחת בצד. שום דבר כאן לא נערך ולא מתפרסם. 'לערוך עכשיו' מתחיל לערוך הקלטה שעוד לא נערכה.",
    "Agent talk": "שיחה עם סוכן",
    "Edited video": "סרטון ערוך",
    "Archive": "לארכיון",
    "Bring it back": "להחזיר",
    "Publish": "פרסום",
    "Hashtags (comma separated)": "האשטגים (מופרדים בפסיק)",
    "Tick at least one place to post.": "צריך לסמן לפחות מקום אחד לפרסום.",
    "Scheduling. The card shows each one as it is booked.": "מתזמן. הכרטיס יראה כל אחד כשהוא נקבע.",
    "Posting. The card shows each link as it goes live.": "מפרסם. הכרטיס יראה כל קישור כשהוא עולה.",
    "On the server. Nothing has been done to it yet.": "בשרת. עוד לא נעשה איתו כלום.",
    "Being transcribed.": "מתמלל.",
    "Transcribed. Proofreading and the cut come next.": "תומלל. אחר כך הגהה וחיתוך.",
    "Being proofread on your subscription.": "עובר הגהה.",
    "Being cut and captioned.": "נחתך ומקבל כתוביות.",
    "Jennifer is checking the edit.": "ג'ניפר בודקת את העריכה.",
    "The cut is planned and waiting to be rendered.": "החיתוך מתוכנן ומחכה לבנייה.",
    "The cut would change what you said. It needs your eyes.": "החיתוך היה משנה את מה שאמרת. צריך שתסתכל.",
    "Edited and ready.": "ערוך ומוכן.",
    "Something went wrong. The original recording is safe.": "משהו השתבש. ההקלטה המקורית שמורה.",
    "Archived without an edit. Nothing is done to it until you tap Edit this now.":
      "בארכיון בלי עריכה. שום דבר לא ייעשה איתו עד שתלחץ 'לערוך עכשיו'.",
    "Edit this now": "לערוך עכשיו",
    "Watch the edit": "לצפות בעריכה",
    "Watch it": "לצפות",
    "Watch the original": "לצפות במקור",
    "Captions": "כתוביות",
    "Transcript": "תמלול",
    "Request an editing change": "לבקש שינוי בעריכה",
    "Edit it again": "לערוך שוב",
    "It is fine, let it through": "זה בסדר, לאשר",
    "Ask Jennifer to check it again": "לבקש מג'ניפר לבדוק שוב",
    "Record it again": "להקליט שוב",
    "Instagram Reel": "רילס באינסטגרם",
    "Facebook Page": "עמוד הפייסבוק",
    "YouTube Short": "שורטס ביוטיוב",
    "Jennifer": "ג'ניפר",
    "Checked by Jennifer": "נבדק על ידי ג'ניפר",
    "Checked and fixed by Jennifer": "נבדק ותוקן על ידי ג'ניפר",
    "Jennifer is holding this": "ג'ניפר עוצרת את זה",
    "Jennifer found something": "ג'ניפר מצאה משהו",
    "You let it through": "אישרת את זה",
    "Not checked": "לא נבדק",
    "Jennifer is holding this video.": "ג'ניפר עוצרת את הסרטון הזה.",
    "The planned cut would change what you said.": "החיתוך המתוכנן היה משנה את מה שאמרת.",
    "Jennifer has not answered yet, so this edit used the rules. It edits itself again when her review lands.":
      "ג'ניפר עוד לא ענתה, אז העריכה הזאת לפי הכללים. היא תיערך שוב כשהבדיקה שלה תגיע.",
    "Jennifer could not review this one, so the rules decided what to cut.": "ג'ניפר לא הצליחה לבדוק את זה, אז הכללים קבעו מה לחתוך.",
    "Jennifer's answer was not usable, so the rules decided what to cut.": "התשובה של ג'ניפר לא הייתה שמישה, אז הכללים קבעו מה לחתוך.",
    "Jennifer's review wants a cut that would change what you said, so the edit you have stays. Edit it again to see her cut and decide.":
      "ג'ניפר רוצה חיתוך שהיה משנה את מה שאמרת, אז העריכה הנוכחית נשארת. לערוך שוב כדי לראות את החיתוך שלה ולהחליט.",
    "You changed the words after Jennifer started reading, so that review was not used. Edit it again for a fresh one.":
      "שינית את המילים אחרי שג'ניפר התחילה לקרוא, אז הבדיקה הזאת לא נכנסה. לערוך שוב לבדיקה חדשה.",
    "(untitled recording)": "(הקלטה בלי שם)",
    "Give her a note to fix it, or let it through if it is fine as it is.": "אפשר לתת לה הערה לתיקון, או לאשר אם זה בסדר כמו שזה.",
    "Jennifer is checking this edit. The card shows each thing she checks as she goes.": "ג'ניפר בודקת את העריכה. הכרטיס יראה כל דבר שהיא בודקת.",
    "Let this video through as it is? Jennifer's finding stays on its record.": "לאשר את הסרטון כמו שהוא? מה שג'ניפר מצאה יישאר מתועד.",
    "Let through. The video is ready, and its posts are being written.": "אושר. הסרטון מוכן, והפוסטים שלו נכתבים.",
    "Edit this video again with the tight cut and the new captions? The current edit is replaced when the new one is ready.":
      "לערוך את הסרטון שוב עם החיתוך ההדוק והכתוביות החדשות? העריכה הנוכחית תוחלף כשהחדשה תהיה מוכנה.",
    "Editing it again. The card shows each step as it happens.": "עורך שוב. הכרטיס יראה כל שלב כשהוא קורה.",
    "Editing it now. It left Archived: find it under Still to do, where the card shows each step.":
      "עורך עכשיו. הוא יצא מהארכיון: הוא נמצא תחת 'עוד לעשות', והכרטיס יראה כל שלב.",
    "Editing it now. The card shows each step as it happens.": "עורך עכשיו. הכרטיס יראה כל שלב כשהוא קורה.",
    "Archived. It is under the Archived filter, and nothing was deleted.": "הועבר לארכיון. הוא נמצא תחת 'בארכיון', ושום דבר לא נמחק.",
    "Back in your Library.": "חזר לספרייה שלך.",
    "Close": "סגירה",
    "What should change about this video? Say it the way you would say it to Jennifer, your video editor.":
      "מה צריך לשנות בסרטון?\n\nאומרים את זה כמו שהיית אומר לג'ניפר, העורכת שלך.",
    "Added to the notes you are giving on this video. It is made with them when you tap Make the new version.":
      "נוסף להערות שאתה נותן על הסרטון. זה ייעשה יחד איתן כשתלחץ 'ליצור את הגרסה החדשה'.",
    "Asked. TCE is making the change now on your subscription; this card updates as it goes.":
      "ביקשת. TCE עושה את השינוי עכשיו; הכרטיס יתעדכן תוך כדי.",
    "To bring one back, use Request an editing change.": "כדי להחזיר משהו, משתמשים ב'לבקש שינוי בעריכה'.",

    // Jennifer's rules
    "Reading the rules Jennifer learned from your notes": "קורא את הכללים שג'ניפר למדה מההערות שלך",
    "Each rule came from a note you gave on a video. Jennifer applies them to every next video, when she edits it and when she checks it. Delete one and she stops using it.":
      "כל כלל הגיע מהערה שנתת על סרטון. ג'ניפר מיישמת אותם בכל סרטון הבא, כשהיא עורכת וכשהיא בודקת. מוחקים כלל והיא מפסיקה להשתמש בו.",
    "No rules yet": "עוד אין כללים",
    "When a note you give Jennifer on a video is about more than that one video, it shows up here.":
      "כשהערה שאתה נותן לג'ניפר על סרטון נוגעת ליותר מהסרטון הזה, היא מופיעה כאן.",
    "Not used right now: Jennifer reads only the newest rules that fit, and this one is older. Delete a rule you no longer need to bring it back.":
      "לא בשימוש כרגע: ג'ניפר קוראת רק את הכללים החדשים שנכנסים, והכלל הזה ישן יותר. מחיקה של כלל שכבר לא צריך תחזיר אותו.",
    "The video it came from is no longer in your Library.": "הסרטון שממנו הוא הגיע כבר לא בספרייה שלך.",
    "Delete this rule": "למחוק את הכלל",
    "Back to the Library": "חזרה לספרייה",
    "Delete this rule? Jennifer stops applying it from the next video on.": "למחוק את הכלל? ג'ניפר תפסיק ליישם אותו מהסרטון הבא.",
    "Deleted. Jennifer no longer applies that rule.": "נמחק. ג'ניפר כבר לא מיישמת את הכלל הזה.",

    // The notes sheet (workspace.js, talk-voice.js; his login types its notes)
    "Jennifer is reading them.": "ג'ניפר קוראת אותן.",
    "The version from before these notes was put back.": "הגרסה שלפני ההערות האלה הוחזרה.",
    "Could not open the Library": "לא הצלחתי לפתוח את הספרייה",
    "Opening your notes on this video": "פותח את ההערות שלך על הסרטון",
    "Your notes open when this is done": "ההערות שלך ייפתחו כשזה יסתיים",
    "Your notes did not open": "ההערות שלך לא נפתחו",
    "Hold to talk did not load on this page. Reload it to talk; Type still saves a note.": "הדיבור לא נטען בדף הזה. הקלדה עדיין שומרת הערה.",
    "The video was edited again, so the new version is in the player now. Your notes moved with it.":
      "הסרטון נערך שוב, אז הגרסה החדשה בנגן עכשיו. ההערות שלך עברו איתה.",
    "There is no edited file to play yet.": "עוד אין קובץ ערוך לנגן.",
    "Not yet": "עוד לא",
    "Starting the new version": "מתחיל את הגרסה החדשה",
    "Making the new version": "יוצר את הגרסה החדשה",
    "Open the notes again": "לפתוח שוב את ההערות",
    "Make the new version (no notes yet)": "ליצור את הגרסה החדשה (עוד אין הערות)",
    "Type a note at the paused second": "להקליד הערה בשנייה שבה עצרת",
    "Your note at": "ההערה שלך בשנייה",
    "Save the note at": "לשמור את ההערה בשנייה",
    "What is wrong at this moment? For example: cut the second basically.": "מה לא בסדר ברגע הזה? למשל: לחתוך את ה'בעצם' השני.",
    "Write what is wrong at this moment first.": "קודם כותבים מה לא בסדר ברגע הזה.",
    "The video was edited again, so the new version is in the player now. Your words are still in the box: pause where they belong and save again.":
      "הסרטון נערך שוב, אז הגרסה החדשה בנגן עכשיו. המילים שלך עדיין בתיבה: עוצרים איפה שהן שייכות ושומרים שוב.",
    "That note could not be saved. Your words are still in the box.": "לא הצלחתי לשמור את ההערה. המילים שלך עדיין בתיבה.",
    "Your notes changed, so here they are again": "ההערות שלך השתנו, אז הנה הן שוב",
    "Make the new version from these notes?": "ליצור גרסה חדשה מההערות האלה?",
    "Nothing changes until you tap Yes. Then Jennifer reads every note, and the video renders once.":
      "שום דבר לא משתנה עד שלוחצים כן. אז ג'ניפר קוראת כל הערה, והסרטון נבנה פעם אחת.",
    "Jennifer is reading every note now. The bar says each step, and each note says what was done with it.":
      "ג'ניפר קוראת עכשיו כל הערה. השורה למטה מראה כל שלב, וכל הערה תגיד מה נעשה איתה.",
    "The video was edited again after these notes. They moved to the new version, which is in the player now: check them, then make the new version.":
      "הסרטון נערך שוב אחרי ההערות האלה. הן עברו לגרסה החדשה, שבנגן עכשיו: בודקים אותן, ואז יוצרים את הגרסה החדשה.",
    "There are no notes with words yet. Hold to talk, or tap Type.": "עוד אין הערות עם מילים. לוחצים על הקלדה וכותבים.",
    "Opening new notes on this version": "פותח הערות חדשות על הגרסה הזאת",
    "No notes yet. Pause where something is wrong, then hold to talk.": "עוד אין הערות. עוצרים במקום שמשהו לא בסדר וכותבים הערה.",
    "Pause where something is wrong, then hold to talk.": "עוצרים במקום שמשהו לא בסדר וכותבים הערה.",
    "No words were caught here.": "לא נקלטו כאן מילים.",
    "Listening for your words": "מקשיב למילים שלך",
    "This one needs you.": "זה מחכה לך.",
    "Being made into the new version.": "נכנס לגרסה החדשה.",
    "Your notes are being made into a new version.": "ההערות שלך נכנסות לגרסה חדשה.",
    "Your new version is being made.": "הגרסה החדשה שלך בהכנה.",
    "These notes were handed to Jennifer. Open the notes again for new ones.": "ההערות האלה הועברו לג'ניפר. פותחים שוב את ההערות כדי לתת חדשות.",
    "Jennifer is reading this note.": "ג'ניפר קוראת את ההערה.",
    "Jennifer has not confirmed this one. It is still made as you said it.": "ג'ניפר עוד לא אישרה את זו. היא עדיין תיעשה כמו שכתבת.",
    "These notes were closed on another screen. Hold to talk opens them again.": "ההערות האלה נסגרו במסך אחר.",
    "That hold was not kept as a note.": "זה לא נשמר כהערה.",
    "That note could not be saved.": "לא הצלחתי לשמור את ההערה.",
    "Hold to talk": "להחזיק ולדבר",
    "Sign in to the voice": "התחברות לקול",
    "Saved": "נשמר",
    "Your notes on this video are being made into a new version right now. Add this once it is done.":
      "ההערות שלך על הסרטון נכנסות עכשיו לגרסה חדשה. אפשר להוסיף את זה כשזה יסתיים.",
    "No words were caught for this note, so it was left out of the new version.": "לא נקלטו מילים בהערה הזאת, אז היא לא נכנסה לגרסה החדשה.",
    "The new version cut this moment; the note now sits where that cut is.": "הגרסה החדשה חתכה את הרגע הזה; ההערה נמצאת עכשיו במקום החיתוך.",
    "This hold was an instruction to Jennifer, not a note.": "זו הייתה הוראה לג'ניפר, לא הערה.",
    "No words were caught for this note, so it was taken back when the notes closed.": "לא נקלטו מילים בהערה הזאת, אז היא בוטלה כשההערות נסגרו.",
    "These notes were closed. Open the notes again to give new ones.": "ההערות האלה נסגרו. פותחים שוב את ההערות כדי לתת חדשות.",
    "This edit was made before notes could be pinned to it. Tap Edit it again, then give your notes.":
      "העריכה הזאת נעשתה לפני שאפשר היה להצמיד לה הערות. לוחצים 'לערוך שוב', ואז נותנים הערות.",
    "There is no edit of this video to give notes on yet.": "עוד אין עריכה של הסרטון הזה לתת עליה הערות.",
    "These notes were already handed to the editor, so they cannot be closed.": "ההערות האלה כבר הועברו לעורכת, אז אי אפשר לסגור אותן.",
    "Jennifer took this as only about this video.": "ג'ניפר הבינה שזה נוגע רק לסרטון הזה.",
    "Jennifer is working out whether this is a rule for every video.": "ג'ניפר בודקת אם זה כלל לכל סרטון.",
    "The video was changed again after these notes, so going back would undo that too. Nothing was changed.":
      "הסרטון השתנה שוב אחרי ההערות האלה, אז חזרה אחורה הייתה מבטלת גם את זה. שום דבר לא השתנה.",
    "The version from before these notes is being put back right now.": "הגרסה שלפני ההערות האלה מוחזרת עכשיו.",
    "These notes have not been made into a new version yet.": "ההערות האלה עוד לא נכנסו לגרסה חדשה.",
    "The new version from these notes is still being made.": "הגרסה החדשה מההערות האלה עדיין בהכנה.",
    "The version from before these notes was already put back.": "הגרסה שלפני ההערות האלה כבר הוחזרה.",
    "These notes did not change the video, so there is nothing to go back from.": "ההערות האלה לא שינו את הסרטון, אז אין ממה לחזור.",
    "Putting back the version from before your notes": "מחזיר את הגרסה שלפני ההערות שלך",
    "These notes were already handed to the editor. Open the notes again for new ones.": "ההערות האלה כבר הועברו לעורכת. פותחים שוב את ההערות כדי לתת חדשות.",
    "The player is on another edit of this video. Load the new one and pause again.": "הנגן על עריכה אחרת של הסרטון. טוענים את החדשה ועוצרים שוב.",
    "That note is already being worked on.": "כבר עובדים על ההערה הזאת.",
    "That note was taken back.": "ההערה בוטלה.",
    "The video was edited again after you gave these notes. Open your notes again: they move to the new version, and then you can make it.":
      "הסרטון נערך שוב אחרי שנתת את ההערות. פותחים שוב את ההערות: הן עוברות לגרסה החדשה, ואז אפשר ליצור אותה.",
    "There are no notes to make a new version from yet.": "עוד אין הערות ליצור מהן גרסה חדשה.",

    // Recording studio (recording.js)
    "Back to the list": "חזרה לרשימה",
    "No signal: kept on this phone": "אין קליטה: נשמר בטלפון",
    "The opening cannot be changed for this take set.": "אי אפשר להחליף את הפתיחה בהקלטה הזאת.",
    "Working": "עובד",
    "More openings are ready.": "פתיחות נוספות מוכנות.",
    "Asked. The engine writes them on your PC worker; this can take a few minutes if it is busy.":
      "ביקשת. המנוע כותב אותן עכשיו; זה יכול לקחת כמה דקות.",
    "This browser cannot record camera video with audio.": "הדפדפן הזה לא יכול להקליט וידאו עם קול.",
    "The recording has no active microphone track.": "אין בהקלטה מיקרופון פעיל.",
    "The phone switched the camera off. What you recorded is kept - press Record to go on.":
      "הטלפון כיבה את המצלמה. מה שהקלטת נשמר - לוחצים הקלטה כדי להמשיך.",
    "The camera did not open.": "המצלמה לא נפתחה.",
    "Some of the video is still on this phone. Reconnect and press Finish again.": "חלק מהסרטון עדיין בטלפון. מתחברים שוב ולוחצים סיום שוב.",
    "That take was too short to keep. Press Record again.": "הטייק היה קצר מדי. לוחצים הקלטה שוב.",
    "Finish at least one clip before finishing the session.": "צריך לסיים לפחות קליפ אחד לפני שמסיימים.",
    "Keeping everything on this phone until you are back online": "שומר הכול בטלפון עד שתחזור לרשת"
  };

  // The weekday letters an Israeli reads in a date ("ביום ה' 8.10"), Sunday first.
  var HE_DAYS = ["א'", "ב'", "ג'", "ד'", "ה'", "ו'", "שבת"];
  var EN_DAYS = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  var EN_MONTHS = { Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6, Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12 };

  /* 6-Oct: the subscription banner printed the provider's raw text twice and an ISO
     time. His login reads one line: when the work resumes, in Israel time. The server
     writes UTC; one without a zone mark is UTC too. */
  function israelParts(iso) {
    var s = String(iso || "");
    if (!/Z$|[+-]\d\d:?\d\d$/.test(s)) s += "Z";
    var d = new Date(s);
    if (isNaN(d.getTime())) return null;
    try {
      var parts = {};
      new Intl.DateTimeFormat("en-US", {
        timeZone: "Asia/Jerusalem", weekday: "short", day: "numeric", month: "numeric",
        hour: "2-digit", minute: "2-digit", hourCycle: "h23"
      }).formatToParts(d).forEach(function (p) { parts[p.type] = p.value; });
      return { day: HE_DAYS[EN_DAYS[parts.weekday]], date: Number(parts.day) + "." + Number(parts.month),
               time: parts.hour + ":" + parts.minute };
    } catch (e) {
      return null;
    }
  }

  function capacityLine(iso) {
    var p = israelParts(iso);
    return p ? "המערכת בהפסקה קצרה וחוזרת לעבוד ביום " + p.day + " " + p.date + " בשעה " + p.time
             : "המערכת בהפסקה קצרה וחוזרת לעבוד בקרוב";
  }

  // "Thu 8-Oct at 00:00" (the server's Israel time, today.israel_time) in Hebrew.
  function heWhen(text) {
    var m = /^(Sun|Mon|Tue|Wed|Thu|Fri|Sat) (\d{1,2})-([A-Z][a-z]{2}) at (\d{1,2}:\d\d)$/.exec(String(text || "").trim());
    if (!m || !EN_MONTHS[m[3]]) return text;
    return "יום " + HE_DAYS[EN_DAYS[m[1]]] + " " + Number(m[2]) + "." + EN_MONTHS[m[3]] + " בשעה " + m[4];
  }

  function tr(text) {
    var out = translate(text);
    return out === null ? text : out;
  }

  function count(n, one, many) { return Number(n) === 1 ? one : n + " " + many; }

  var FLAG_WORDS = {
    "makes a promise": "מבטיח הבטחה", "names someone from a call": "מזכיר מישהו משיחה",
    "has an email address": "יש בו כתובת מייל", "has a phone number": "יש בו מספר טלפון",
    "names an amount of money": "מזכיר סכום כסף", "gives a revenue percentage": "נותן אחוז הכנסות",
    "quotes a customer": "מצטט לקוח", "looks like a password or key": "נראה כמו סיסמה או מפתח",
    "has a private link": "יש בו קישור פרטי", "was flagged": "סומן"
  };
  var PACKET_STATES = { ready: "מוכן", exported: "מוכן", draft: "טיוטה", superseded: "הוחלף", blocked: "חסום" };

  // Topic filter names as the page writes them inside a count ("3 ideas best matches").
  var FILTER_NAMES = {
    "best matches": "הכי מתאימים", "calls": "שיחות", "code": "קוד", "ai news": "חדשות AI",
    "evergreen": "תמיד רלוונטי", "later": "אחר כך", "put away": "בצד"
  };

  var PATTERNS = [
    // 6-Oct: the capacity banner is one Hebrew line, never the provider's text or ISO.
    [/^Subscription capacity: [\s\S]*; resumes at (\S+)$/, function (_, iso) { return capacityLine(iso); }],
    [/^Waiting for subscription capacity: [\s\S]*$/, "המערכת בהפסקה קצרה וחוזרת לעבוד בקרוב"],
    [/^Something went wrong \((\d+)\)\.$/, "משהו השתבש ($1)."],
    // Today's next step (today.py)
    [/^(\d+) changes? are waiting for your yes or no\.$/, "$1 שינויים מחכים לכן או לא שלך."],
    [/^(\d+) ideas are waiting for a decision\.$/, "$1 רעיונות מחכים להחלטה."],
    [/^(\d+) of your (\d+) topics still needs a script\. (?:(\d+) more (?:is|are) on the way and (?:saves itself|save themselves)\. )?Each one is written on your PC worker\.$/,
      function (_, a, b, c) {
        return a + " מתוך " + b + " הנושאים שלך עוד צריכים תסריט. "
          + (c ? c + " נוספים בדרך ונשמרים לבד. " : "") + "כל תסריט נכתב אוטומטית.";
      }],
    [/^(?:Your script waits|(\d+) scripts wait) for your Claude limit to reset on (.+?)\. (?:It is|They are) written then and (?:saves itself|save themselves); nothing to ask again\.$/,
      function (_, n, when) {
        return (n ? n + " תסריטים מחכים" : "התסריט שלך מחכה") + " שהמנוי יתחדש, " + heWhen(when)
          + ". " + (n ? "הם ייכתבו אז וישמרו לבד" : "הוא ייכתב אז וישמר לבד") + "; אין צורך לבקש שוב.";
      }],
    [/^(?:Your script is|(\d+) scripts are) being written on your PC worker and (?:saves itself|save themselves); nothing to do until then\.$/,
      function (_, n) {
        return (n ? n + " תסריטים נכתבים עכשיו ונשמרים לבד" : "התסריט שלך נכתב עכשיו ונשמר לבד") + "; אין מה לעשות עד אז.";
      }],
    // Script requests (status.py)
    [/^Waiting for your Claude limit to reset(?: on (.+?))?\. The script is written then and saves itself; nothing to ask again\.$/,
      function (_, when) {
        return "מחכה שהמנוי יתחדש" + (when ? ", " + heWhen(when) : "") + ". התסריט ייכתב אז וישמר לבד; אין צורך לבקש שוב.";
      }],
    [/^([\s\S]+?) It takes the place of this script when it is saved; if you film this script first, the new one is kept aside\.$/,
      function (_, first) { return tr(first) + " הוא יחליף את התסריט הזה כשיישמר; אם תצלם את התסריט הזה קודם, החדש יישמר בצד."; }],
    [/^The last try stopped \(([^)]*)\)\. Ask again\.$/, "הניסיון האחרון נעצר ($1). אפשר לבקש שוב."],
    // Topics and the week
    [/^(\d+) of (\d+) shown(?:\. ([\s\S]*))?$/, function (_, a, b, note) {
      return "מוצגים " + a + " מתוך " + b + (note ? ". " + tr(note) : "");
    }],
    [/^Went stale on (.+)$/, "כבר לא טרי מאז $1"],
    [/^Worth saying until (.+)$/, "רלוונטי עד $1"],
    [/^From your note: ([\s\S]*)$/, "מההערה שלך: $1"],
    [/^From the video: ([\s\S]*)$/, "מהסרטון: $1"],
    [/^From (.+), (.+) and (\d+) more$/, "מתוך $1, $2 ועוד $3"],
    [/^Here because ([\s\S]*)$/, "כאן כי $1"],
    [/^Record first because ([\s\S]*)$/, "להקליט ראשון כי $1"],
    [/^(\d+) videos this week, (\d+) more than your usual (\d+)\. A good week\.(?: ([\s\S]*))?$/,
      function (_, a, b, c, rest) {
        return a + " סרטונים השבוע, " + b + " יותר מהרגיל שלך (" + c + "). שבוע טוב." + (rest ? " " + tr(rest) : "");
      }],
    [/^Open Topics and put (\d+) ideas? in this week, or more on a good week\.$/,
      "פותחים את נושאים ומכניסים $1 רעיונות לשבוע, או יותר בשבוע טוב."],
    [/^(\d+) of (\d+) scripts? ready, (\d+) filmed$/, "$1 מתוך $2 תסריטים מוכנים, $3 צולמו"],
    [/^In this week's list at number (\d+)\.$/, "ברשימה של השבוע, במקום $1."],
    // The topic page and the script workshop
    [/^Version (\d+) \(current\)$/, "גרסה $1 (נוכחית)"],
    [/^Version (\d+), (\w+)\.$/, function (_, v, s) { return "גרסה " + v + ", " + (PACKET_STATES[s] || s) + "."; }],
    [/^Saved as version (\d+)\. The old one is in History\.$/, "נשמר כגרסה $1. הקודמת בהיסטוריה."],
    [/^That is your opening now\. Saved as version (\d+)\.$/, "זו הפתיחה שלך עכשיו. נשמר כגרסה $1."],
    [/^Edit (.+)$/, function (_, what) { return "עריכה: " + tr(what); }],
    [/^(\d+) points?, (\d+) lines?\.$/, function (_, a, b) {
      return count(a, "נקודה אחת", "נקודות") + ", " + count(b, "שורה אחת", "שורות") + ".";
    }],
    [/^This version has (\d+) flagged lines?\. Check before recording\.$/, "בגרסה הזאת סומנו $1 שורות. כדאי לבדוק לפני ההקלטה."],
    [/^Line (\d+)$/, "שורה $1"],
    [/^Recommended · in use$/, "מומלץ · בשימוש"],
    [/^Option (\d+) · in use$/, "אפשרות $1 · בשימוש"],
    [/^That one is already (\w+)\.$/, "זה כבר טופל."],
    // Settings
    [/^Saved\. Your week is now (\d+) videos?\.$/, "נשמר. השבוע שלך עכשיו $1 סרטונים."],
    [/^Could not turn them on: ([\s\S]*)$/, function (_, why) { return "לא הצלחתי להפעיל: " + tr(why); }],
    // Library cards
    [/^(\d+) open requests?$/, "$1 בקשות פתוחות"],
    [/^(.+) with (.+): a voice call you filmed\. Jennifer keeps (.+)'s lines and cuts the dead air\.$/,
      "$1 עם $2: שיחה קולית שצילמת. ג'ניפר שומרת את מה ש$3 אמר וחותכת את השקט."],
    [/^Agent talk with (.+)$/, "שיחה עם $1"],
    [/^Proofread fixed: ([\s\S]*)$/, "תוקן בהגהה: $1"],
    [/^Your phone cut a word short:$/, "הטלפון קטע מילה:"],
    [/^Your phone cut (\d+) words short:$/, "הטלפון קטע $1 מילים:"],
    [/^([\s\S]*)\. Say the line again, or ask for a patch in Request an editing change\.$/, function (_, said) {
      return said.replace(/” at (\d+:\d\d)/g, "” בשנייה $1")
        + ". אפשר להגיד את השורה שוב, או לבקש תיקון ב'לבקש שינוי בעריכה'.";
    }],
    [/^Took out (\d+) things?$/, function (_, n) { return n === "1" ? "הוצא דבר אחד" : "הוצאו " + n + " דברים"; }],
    [/^\(you asked: ([\s\S]*)\)$/, "(ביקשת: $1)"],
    [/^(\d+) notes? waiting - Make the new version$/, "$1 הערות מחכות - ליצור את הגרסה החדשה"],
    [/^Making the new version from your (\d+) notes?:$/, "יוצר את הגרסה החדשה מ-$1 ההערות שלך:"],
    [/^Your last (\d+) notes?(?:: (\d+) needs? you)?$/, function (_, n, k) {
      return (n === "1" ? "ההערה האחרונה שלך" : n + " ההערות האחרונות שלך") + (k ? ": " + k + " מחכות לך" : "");
    }],
    [/^Applied on (\d+) videos?(?: · learned (.+))?$/, function (_, n, when) {
      return "יושם ב-" + n + " סרטונים" + (when ? " · נלמד ב-" + when : "");
    }],
    [/^Not applied on a video yet(?: · learned (.+))?$/, function (_, when) {
      return "עוד לא יושם על סרטון" + (when ? " · נלמד ב-" + when : "");
    }],
    [/^Open the video it came from: ([\s\S]*)$/, "לפתוח את הסרטון שממנו זה הגיע: $1"],
    [/^(\d+) rules?$/, function (_, n) { return n === "1" ? "כלל אחד" : n + " כללים"; }],
    [/^Jennifer learned a rule from this: ([\s\S]*)$/, "ג'ניפר למדה מזה כלל: $1"],
    [/^Jennifer already has a rule for this: ([\s\S]*)$/, "לג'ניפר כבר יש כלל לזה: $1"],
    [/^Put back the version from before your (\d+) notes?$/, "להחזיר את הגרסה שלפני $1 ההערות שלך"],
    [/^Reading your (\d+) notes? on the subscription$/, "קורא את $1 ההערות שלך"],
    [/^(\d+) notes? still waiting here, so these notes stay open\.$/, "$1 הערות עוד מחכות כאן, אז ההערות האלה נשארות פתוחות."],
    // The notes sheet
    [/^Yes, make it \((\d+) notes?\)$/, "כן, ליצור ($1 הערות)"],
    [/^Make the new version \((\d+) notes?\)$/, "ליצור את הגרסה החדשה ($1 הערות)"],
    [/^Making the new version \((\d+) notes?\)$/, "יוצר את הגרסה החדשה ($1 הערות)"],
    [/^Saving the note at (\S+)$/, "שומר את ההערה בשנייה $1"],
    [/^Saved your note at (\S+)\.$/, "ההערה שלך נשמרה בשנייה $1."],
    [/^Saved at (\S+)$/, "נשמר בשנייה $1"],
    [/^You said: ([\s\S]*)$/, "כתבת: $1"],
    [/^Take back the note at (\S+)$/, "לבטל את ההערה בשנייה $1"],
    // The studio: what the safety check flagged
    [/^Script version (\S+) is not ready to record: the safety check did not pass it\.$/,
      "התסריט, גרסה $1, לא מוכן להקלטה: בדיקת הבטיחות לא העבירה אותו."],
    [/^Script version (\S+) was replaced by a newer version, so it is not the one to record\.$/,
      "התסריט, גרסה $1, הוחלף בגרסה חדשה יותר, אז לא אותו מקליטים."],
    [/^Script version (\S+) is not ready to record\. The check flagged (?:this line|these (\d+) lines):$/,
      function (_, v, n) { return "התסריט, גרסה " + v + ", לא מוכן להקלטה. הבדיקה סימנה " + (n ? n + " שורות" : "את השורה הזאת") + ":"; }],
    [/^(Point|Line) (\d+) (makes a promise|names someone from a call|has an email address|has a phone number|names an amount of money|gives a revenue percentage|quotes a customer|looks like a password or key|has a private link|was flagged)(: [\s\S]*)?$/,
      function (_, kind, n, what, words) {
        return (kind === "Point" ? "נקודה " : "שורה ") + n + " " + FLAG_WORDS[what] + (words || "");
      }],
    [/^Recommended · current opening$/, "מומלץ · הפתיחה הנוכחית"],
    [/^Option (\d+) · current opening$/, "אפשרות $1 · הפתיחה הנוכחית"],
    [/^(\d+) ideas? (?:is|are) not shown because the engine could not say how they connect to your work\.$/, "$1 רעיונות לא מוצגים כי המנוע לא הצליח להסביר איך הם קשורים לעבודה שלך."],
    [/^(\d+) of (\d+) scripts? ready$/, "$1 מתוך $2 תסריטים מוכנים"],
    [/^Week of (\S+)$/, "השבוע של $1"],
    [/^(\d+) recordings?$/, "$1 הקלטות"],
    [/^(\d+) videos? a week$/, "$1 סרטונים בשבוע"],
    [/^(\d+) ideas? (best matches|calls|code|ai news|evergreen|later|put away)$/i, function (_, n, f) {
      return n + " רעיונות · " + FILTER_NAMES[f.toLowerCase()];
    }],
    [/^(\d+) of (\d+) videos? planned\.(?: (\d+) other\.)?$/, function (_, a, b, o) {
      return a + " מתוך " + b + " סרטונים מתוכננים." + (o ? " " + o + " אחר." : "");
    }],
    [/^Save (\d+) a week$/, "לשמור $1 בשבוע"],
    [/^(\d+) of (\d+) · Start a new take set$/, "$1 מתוך $2 · הקלטה חדשה"],
    [/^(\d+) of (\d+) · Continue take set .*$/, "$1 מתוך $2 · ממשיכים את ההקלטה"],
    [/^(\d+) of (\d+) · Being put together for editing$/, "$1 מתוך $2 · מחברים לעריכה"],
    [/^Point (\d+)$/, "נקודה $1"],
    // Lines on his post card that the server writes in English (5-Oct).
    [/^Changing: ([\s\S]*)$/, "משנה: $1"],
    [/^(\d+) worker\(s\) online$/, "$1 מחשבים מחוברים"],
    [/^Worker refused by policy: ([\s\S]*)$/, "העבודה נעצרה לפי מדיניות: $1"],
    [/^Changed as you asked: ([\s\S]*)$/, "שונה כמו שביקשת: $1"],
    [/^The change did not run \(([^)]*)\); ask again$/, "השינוי לא רץ ($1); אפשר לבקש שוב"],
    [/^The change stopped: ([\s\S]*)$/, "השינוי נעצר: $1"],
    [/^Check before posting: it talks about how an effect is done \('([\s\S]*)'\)$/, "לבדוק לפני פרסום: יש כאן משהו על איך אפקט נעשה ('$1')"],
    [/^Version (\d+)$/, "גרסה $1"],
    [/^Script version (\d+)$/, "תסריט, גרסה $1"],
    [/^Option (\d+)$/, "אפשרות $1"],
    [/^(\d+) ready scripts?$/, "$1 תסריטים מוכנים"],
    [/^(\d+) ideas? waiting$/, "$1 רעיונות מחכים"],
    [/^(\d+) other$/, "$1 אחר"],
    [/^([\s\S]+) is first\.$/, "$1 ראשון."],
    [/^Recommended(.*)$/, "מומלץ$1"],
    [/^Why \(private\): ([\s\S]*)$/, "למה (רק לך): $1"],
    [/^Viewer question: ([\s\S]*)$/, "השאלה של הצופה: $1"],
    [/^Recording did not start: ([\s\S]*)$/, "ההקלטה לא התחילה: $1"],
    [/^The camera did not come back: ([\s\S]*)$/, "המצלמה לא חזרה: $1"],
    [/^Lost contact while waiting: ([\s\S]*)$/, "הקשר נותק בזמן ההמתנה: $1"],
    [/^Opening changed\. Packet version (\d+) is bound to this take set\.$/, "הפתיחה הוחלפה. גרסה $1 מחוברת להקלטה הזאת."]
  ];

  function translate(text) {
    if (typeof text !== "string") return null;
    var key = text.trim();
    if (!key) return null;
    var flat = key.replace(/\s+/g, " ");
    if (Object.prototype.hasOwnProperty.call(EXACT, flat)) return text.replace(key, EXACT[flat]);
    for (var i = 0; i < PATTERNS.length; i += 1) {
      if (PATTERNS[i][0].test(flat)) return text.replace(key, flat.replace(PATTERNS[i][0], PATTERNS[i][1]));
    }
    // A label the page writes with a colon after it ("Needs you:", "Done:").
    var bare = flat.replace(/:$/, "");
    if (bare !== flat && Object.prototype.hasOwnProperty.call(EXACT, bare)) {
      return text.replace(key, EXACT[bare].replace(/\.$/, "") + ":");
    }
    return null;
  }

  var ATTRS = ["aria-label", "title", "placeholder"];
  var SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, INPUT: 1 };

  function translateNode(node) {
    if (!node) return;
    if (node.nodeType === 3) {
      var parent = node.parentNode;
      if (parent && SKIP[parent.nodeName]) return;
      var out = translate(node.nodeValue);
      if (out !== null && out !== node.nodeValue) node.nodeValue = out;
      return;
    }
    if (node.nodeType !== 1 || node.nodeName === "SCRIPT" || node.nodeName === "STYLE") return;
    ATTRS.forEach(function (name) {
      if (!node.hasAttribute(name)) return;
      var val = node.getAttribute(name);
      var tr = translate(val);
      if (tr !== null && tr !== val) node.setAttribute(name, tr);
    });
    var child = node.firstChild;
    while (child) {
      translateNode(child);
      child = child.nextSibling;
    }
  }

  var api = { lang: "he", translate: translate, translateNode: translateNode, EXACT: EXACT };
  root.TCE_I18N = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;

  if (typeof document === "undefined" || typeof MutationObserver === "undefined") return;
  // Questions the page asks in a browser dialog (delete a rule, let a video through).
  ["confirm", "alert", "prompt"].forEach(function (name) {
    var original = root[name];
    if (typeof original !== "function") return;
    root[name] = function (message) {
      var args = Array.prototype.slice.call(arguments);
      var out = translate(String(message === undefined || message === null ? "" : message));
      if (out !== null) args[0] = out;
      return original.apply(root, args);
    };
  });
  var observer = new MutationObserver(function (records) {
    records.forEach(function (r) {
      if (r.type === "characterData") translateNode(r.target);
      else if (r.type === "attributes") translateNode(r.target);
      else r.addedNodes.forEach(translateNode);
    });
  });
  observer.observe(document.documentElement, {
    childList: true, subtree: true, characterData: true,
    attributes: true, attributeFilter: ATTRS
  });
  function all() {
    translateNode(document.documentElement);
    if (document.title) {
      var t = translate(document.title);
      if (t) document.title = t;
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", all);
  else all();
})(typeof window !== "undefined" ? window : globalThis);
