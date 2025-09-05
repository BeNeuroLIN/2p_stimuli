const int RELAY = 3;   // IN1

void setup() {
  pinMode(RELAY, OUTPUT);
  digitalWrite(RELAY, HIGH);  // for active-LOW boards: HIGH = OFF (idle)
}

void loop() {
  // Turn valve ON for 5 s, OFF for 5 s
  digitalWrite(RELAY, LOW);   // ON (active-LOW)
  delay(5000);
  digitalWrite(RELAY, HIGH);  // OFF
  delay(5000);
}