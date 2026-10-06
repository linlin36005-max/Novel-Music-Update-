# Novel AI Auto Reply Bot

Telegram Group ထဲမှာ keyword auto-reply + Gemini AI auto-reply လုပ်ပေးတဲ့ bot ပါ။

## 1. Environment Variables

Railway Variables ထဲမှာ:

- `BOT_TOKEN` = @BotFather က Telegram bot token
- `GEMINI_API_KEY` = Gemini API key
- `GEMINI_MODEL` = `gemini-3.7-flash` (လိုအပ်ရင် ကိုယ့် account မှာရတဲ့ model ကိုပြောင်း)
- `OWNER_ID` = Owner Telegram user ID (optional)
- `AI_COOLDOWN` = default 3 seconds

Gemini API key ကို code ထဲမထည့်ဘဲ environment variable အဖြစ်ထားထားပါတယ်။

## 2. Telegram Group Setup

Bot ကို Group ထဲထည့်ပြီး **Admin** ပေးပါ။

Bot က Group ထဲက normal messages အားလုံးကိုဖတ်ပြီး AI reply လုပ်ချင်ရင်:
1. @BotFather ကိုသွား
2. `/setprivacy`
3. ကိုယ့် bot ရွေး
4. `Disable`

ပြီးရင် bot ကို Group ထဲ remove/add ပြန်လုပ်နိုင်ပါတယ်။

## 3. Owner Permission

ဒီ version မှာ Group တစ်ခုချင်းစီကို Bot Owner က permission ပေးပြီးမှ Auto Reply အလုပ်လုပ်ပါတယ်။

Bot Owner ရဲ့ Telegram user ID ကို Railway Variable `OWNER_ID` ထဲထည့်ပါ။

ပြီးရင် Group ထဲမှာ Bot Owner ကိုယ်တိုင်:

`/Novel`

ပို့ပါ → `Permission Granted` → Auto Reply စတင်အလုပ်လုပ်မယ်။

ပိတ်ချင်ရင်:

`/Novel off`

ပို့ပါ → အဲဒီ Group မှာ Bot reply ရပ်ပါမယ်။

`/Novel` ကို Bot Owner မဟုတ်တဲ့ user တွေသုံးလို့မရပါ။

## 4. Commands

`/ai on` — AI reply ON  
`/ai off` — AI reply OFF

`/mode keyword` — keyword only  
`/mode ai` — AI only  
`/mode both` — keyword + AI

`/addreply ကဒ်ကျ | ကျဝူး 😂`

`/delreply ကဒ်ကျ`

`/listreply`

`/setprompt မြန်မာလို သူငယ်ချင်းတစ်ယောက်လို တိုတိုနဲ့ ရယ်စရာလေးတွေထည့်ပြီးပြန်ပါ`

`/cooldown 3`

`/status`

## Example

User:
ကဒ်ကျ

Bot:
ကျဝူး 😂

If `/mode both` + `/ai on`:
- Matching keyword → saved reply
- Other normal messages → Gemini reply

## Railway

GitHub repo တင်ပြီး Railway မှာ Deploy လုပ်ပါ။
Variables ထည့်ပြီး Start Command ကို `python bot.py` ထားပါ။

SQLite database ကို local `data/bot.db` မှာသိမ်းပါတယ်။ Railway မှာ persistent volume မသုံးရင် redeploy/restart အချို့အခြေအနေတွေမှာ database ပြန်ပျောက်နိုင်ပါတယ်။ Production အတွက် PostgreSQL သို့မဟုတ် persistent volume သုံးဖို့အကြံပြုပါတယ်။


## Permission Request Message

Permission မပေးရသေးတဲ့ Group မှာ User စာပို့ရင် Bot က 60 စက္ကန့်အတွင်း တစ်ကြိမ်သာ permission တောင်းတဲ့ message ပြပြီး `📩 Owner ဆီ Permission တောင်းမယ်` URL button ထည့်ပေးပါတယ်။ Button က `https://t.me/Novel220` ကိုဖွင့်ပေးပါတယ်.


## Broadcast

Bot Owner only:

`/broadcast မင်္ဂလာပါ Group အားလုံး`

ဒီ command က `/Novel` permission ပေးထားတဲ့ Group တွေအားလုံးကို message ပို့ပေးပါတယ်။

`/Novel off` လုပ်ထားတဲ့ Group ကို broadcast မပို့ပါ။

Broadcast result မှာ Sent / Failed / Total ကို ပြပေးပါတယ်။


## Troubleshooting

After `/Novel` and `/ai on`, run `/testai` as a Group admin/Owner. It checks the Gemini API connection and prints the actual error if the API key, billing, model, or network is wrong.

For automatic replies to ordinary group messages, the bot must be an admin or have Group Privacy Mode disabled. Telegram says bot admins receive all group messages; with privacy mode enabled, ordinary messages are otherwise filtered. If you change `/setprivacy`, re-add the bot to the group.


## Gemini Free API
This version uses Google Gemini instead of OpenAI. Create a Gemini API key in Google AI Studio and set `GEMINI_API_KEY` on Railway. The selected Flash model has a Free Tier subject to Google's current limits.
