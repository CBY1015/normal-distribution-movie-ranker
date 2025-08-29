# Normal-Distribution-Movie-Ranker

This is a movie ranking and rating system that allows users to create personalized movie lists and rank and rate them through an interactive interface.

這是一個電影排名與評分系統，讓使用者可以建立個人化的電影清單，並透過互動式介面為其排名與評分。

-----

## 專案特色

  * **智能資料庫切換**：後端會自動偵測環境，優先使用 **PostgreSQL** 雲端資料庫來確保資料永久保存。若連線失敗，會自動切換至本機 **SQLite** 作為備援，方便開發與測試。
  * **TMDB API 整合**：直接串接 **TMDB (The Movie Database)** API，提供強大的電影搜尋與隨機推薦功能。
  * **互動式排名演算法**：使用 **二分搜尋演算法** 讓使用者透過簡單的「兩部電影擇一」對決，快速將新電影插入到個人化排名清單中。
  * **自動評分計算**：後端根據電影在清單中的排名位置，自動計算 **常態分佈** 或 **線性分佈** 的評分，提供更科學的量化指標。
  * **單頁應用程式 (SPA)**：前端以單一 HTML 頁面實現，提供流暢的使用者體驗，無須重新載入即可完成所有操作。
  * **資料匯出功能**：支援將個人排名清單匯出為 **CSV 格式**，方便匯入至 [Letterboxd](https://letterboxd.com/) 等其他電影服務。

-----

## 直接線上試用

此專案已部署至 **Render.com**，您可以直接透過以下網址體驗完整功能：

[https://normal-distribution-movie-ranker.onrender.com/](https://www.google.com/url?sa=E&source=gmail&q=https://normal-distribution-movie-ranker.onrender.com/)
