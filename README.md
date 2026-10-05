<p align="center"> <img src="static/logo.webp" width="128" height="128" alt="Aryan Brite website logo">
</p>
<h1 align="center">piko.im</h1>

<p align="center"> We’re building a game-like way to learn DSA. You solve problems, earn XP, level up, particiapte in contests, join teams, meet with Piko community and unlock new topics as you go.

</p>

---


<p align="center">
  <img src="https://img.shields.io/badge/Version-bita-orange?style=for-the-badge&labelColor=222222" alt="Version">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge&labelColor=222222" alt="License">
  <img src="https://img.shields.io/badge/Open%20Source-Yes-blue?style=for-the-badge&labelColor=222222" alt="Open Source">
  <img src="https://img.shields.io/badge/Built%20With-Flask-ffd519?style=for-the-badge&labelColor=222222" alt="Built With Flask">
  <img src="https://img.shields.io/badge/Hack%20Club-❤-ec3750?style=for-the-badge&labelColor=222222" alt="Hack Club">
  <img src="https://img.shields.io/badge/Made%20with-❤-red?style=for-the-badge&labelColor=222222" alt="Made with Love">
</p>

> [!IMPORTANT]
> **AI Usage:** 

> Aryan: I use ChatGPT for taking some CSS reference. For example, working with the infinite scroll thing in the hero section, I use ChatGPT to debug some of the stuck issues. The line you see below the text is also made by ChatGPT. That's not a very big deal, though. I occasionally did use ChatGPT for coding, for example, when I was not able to figure out what I am supposed to do. I use ChatGPT for those purposes. I also used Copilot for a while to fix the bugs of the infinite scroll and some backend bugs because I was not aware of the backend, as I am the frontend engineer in this project.

> Adhdhyan: I used Claude Code for making email templates and helped me with some BASIC frontend for the sake of backend testing, it also suggested me options to how to implement compiler in website for DSA problems, also took suggestions for admin tools. Apart from that I ask Claude to fix bugs whichever existed in my code.



> [!NOTE]
> This is a very big project. We aim to make this project a very big SAAS.
> 1) We have implemented features like google/hackclub/discord auth with 2 factor authentication which connects to 1Password/Google Authenticator/Microsoft Authenticator and many more
> 2) We have also implemented developers API for the users as this is a app for future developers. so that they can use our API to get real time data of their profile from their coding agent or community projects
> 3) We have a vey very big admin page which works pritty good. Its very huge and can do almost anything. From managing the User to approving Education Plans/ Universites etc
> 4) We have implemented things like Pro Plan. The content is still free but the Plan includes features which costs us money like AI tutor
> 5) We have a very good security with 2fa in admin panel and we email every user on suspecius logins. (suspecius logins only not all) As we aim to make this a real product
> 6) Tho we have a Pro Plan we also provide Student Plan which is free and give acess to all pro benifits. It works just like github education. Aproval goes manually from our admin dashbord
> 7) Emails are well equiped for OTPs, Messages, Newsletters etc
> 8) University/School teachers can also make a classroom. We have some dedicated pages for classrooms
> 9) The engeneering is almost done except frontend for new pages. We are still polishing and out team is small with a very huge codebase so we still need time to polish our frontend. The infrastructure is done. We have dedicated Author dashboard. Right now we have some small cources which we will delete after we find some volunteers who will be willing to become the author. We have a dedicateed Author dashboard where they will write the some cool content.

## Screenshot
![screenshot](https://cdn.hackclub.com/01a0bf10-6694-7374-a227-ea723ea9cc09/image%20(7).png)


## Tech Stack
- Flask
- Jinja
- HTMX
- AOS
- Neon
- Hack Club, Google, Github and Discord OAuth
- Resend Emails
- Polar Payment gateway
- openai v2 LLM compatable API
- AWS EC2



## Running Locally

1) Clone the repository:

```sh
 git clone https://github.com/Atom-thirdspace/piko.im 
```

2) Set the environment variables according to .env.example

3) 
```sh
pip install -r requirements.txt
python app.py or Flask run #depends on your OS
```
4) Once the server is up, go tp 127.0.0.1:5000


## For Polar Setup
<p>Currently we are using polar sandbox for the payments, and they are not implemented completely, you can get your sandbox credentials from https://sandbox.polar.sh and setup your environment in developer mode for contributions.</p>

---

Made with love, bad decisions, and way too much free time.

© [The MIT LIcense](LICENSE) - Aryan Brite & Adhyys
