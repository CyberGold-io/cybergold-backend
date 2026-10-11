// The actual retained V8 parser is the fixture oracle; timestamps remain strings.
const values=new Set<string>(['','not a date','null','undefined','NaN','Infinity','2026-09-30\0junk']);
for(let n=0;n<110;n++)for(const prefix of ['','0','0000','+','-'])values.add(prefix+n);
for(const year of ['0000','0001','0099','0999','1970','2026','+010000','-000001','+275760','-271821','-000000'])
 for(const month of ['00','01','02','09','12','13','1'])for(const day of ['00','01','28','29','30','31','32','1'])
  values.add(`${year}-${month}-${day}`);
for(const date of ['2026-09-30','2026-09','2026','2026-02-30','2026-9-30','Sep 30 2026','30 September 2026','Wed, 30 Sep 2026'])
 for(const join of ['T','t',' ','  '])for(const clock of ['10:00','10:00:00','10:00:00.1','10:00:00.000000001','24:00:00','24:00:01','25:00','10::00','10:00.00'])
  for(const zone of ['','Z','z','+02:00','-0500',' GMT',' UTC',' PDT','+2','+99:00'])values.add(date+join+clock+zone);
for(const date of ['2026-09-30','9/30/2026','9.30.2026','30-Sep-2026','Sep 30','Sep 2026 30','foo Sep 30 2026'])
 for(const prefix of ['',' ','\ufeff','\u2003','junk ','(comment (nested)) '])for(const suffix of ['',' ',' GMT','foo',' (comment)',' (unterminated',')'])values.add(prefix+date+suffix);
for(const value of ['2026-09-30T10:00:00','2026-09-30T10:00:30','2026-09-30T09:55:00','2026-09-30T09:54:59.999',
 '2026-03-29T02:30:00','2026-10-25T02:30:00','2026-03-08T02:30:00','2026-11-01T01:30:00',
 '2026/9/30 10:00 PM','2026/9/30 12:00 AM','2026/9/30 0:00 PM','2026/9/30 13:00 PM'])values.add(value);
console.log(JSON.stringify({timezone:process.env.TZ,values:[...values].map(text=>({text,value:new Date(text).getTime()}))}));
