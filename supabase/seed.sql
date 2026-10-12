-- Demonstration locations only; replace with school-confirmed data before production.
INSERT INTO public.rooms(id,code,name,building,floor,capacity,equipment,latitude,longitude,map_x,map_y,location_text)
VALUES
('11111111-1111-4111-8111-111111111111','ENG-201','工學院 201','工學院',2,48,ARRAY['投影機','白板','冷氣'],25.1504,121.7759,35,45,'工學院二樓，主樓梯右側走廊第一間。示範位置，請洽系辦確認。'),
('11111111-1111-4111-8111-111111111112','SCI-102','理學院 102','理學院',1,32,ARRAY['投影機','白板'],25.1509,121.7772,58,35,'理學院一樓，正門進入後左側。示範位置，請洽系辦確認。'),
('11111111-1111-4111-8111-111111111113','HUM-305','人文大樓 305','人文大樓',3,80,ARRAY['投影機','麥克風','冷氣'],25.1493,121.7748,24,68,'人文大樓三樓，電梯出口右轉。示範位置，請洽系辦確認。'),
('11111111-1111-4111-8111-111111111114','MAR-203','海洋科學 203','海洋科學館',2,24,ARRAY['白板','冷氣'],25.1513,121.7791,77,28,'海洋科學館二樓，中央樓梯對面。示範位置，請洽系辦確認。')
ON CONFLICT(code) DO NOTHING;
-- Never seed a privileged account or pretend that a sample roster confirms a real identity.
