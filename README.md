# iac-pulumi

1.clone the repository 
2. python -m venv venv //CREATE THE VIRTUAL ENVIRONMENT 
3. .\venv\Scripts\activate //ACTIVATE THE VIRTUUAL ENVIRONMENT 
4. pip install -r requirements.txt //INSTALL THE DEPENDENICES IN THE requirements.txt in VE 
5. open the folder which is cloned in visual studio
6. open an integrated terminal
7. pulumi stack init <stack_name> -d "My Pulumi Stack" //creates a stack with the yaml file which is used for config of aws credentials and other variables 
8.pulumi config set aws:region us-west-2 pulumi config set aws:accessKey <your_access_key> pulumi config set aws:secretKey <your_secret_key> pulumi config set vpc:cidrBlock //setting the configuration for aws and cidr for vpc 
9.pulumi up //to run your pulumi file and setup uo the infrastructure
